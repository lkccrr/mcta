"""mt.server 的 SSH/SFTP 后端。

-R/--ssh 开启后：目录列表与文件内容来自 SFTP，文件正文先下载到本机缓存目录，
再交给现有的文本查看 / ase / 3Dmol 链路。缓存按服务器固定路径、退出不删除，下次复用。远程模式使用四条互相独立的 SSH 通道：
终端交互 shell（RemoteSSH）、目录浏览、上传、下载（后三条由 RemoteFS 各自持有
独立的 SSH + SFTP 连接），因此大文件传输不会阻塞目录列表、终端或其它传输。
除此之外还有第五条独立通道 RemoteRenderChannel：用系统 ssh 把本地回环端口转发到
远端 mt.server 的 Unix socket，只服务 3D 渲染；远端不监听 TCP 端口，失败时回退本地。
本模块负责连接、认证、远程路径、临时缓存与隧道管理，HTTP 路由仍由 _handlers.py 负责。
"""

import atexit
import errno
import getpass
import hashlib
import http.client
import logging
import os
import posixpath
import re
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import weakref
from pathlib import Path
from urllib.parse import unquote

try:
    import paramiko
except ImportError:  # 缺少依赖时给出明确提示，而不是在导入 mt.server 时报错
    paramiko = None


SSH_SPEC_ENV = "MCTA_SERVER_SSH_SPEC"
SSH_ROOT_ENV = "MCTA_SERVER_SSH_ROOT"
# -i/--ident 指定的私钥路径；后台子进程通过环境变量继承，密钥内容不进入环境。
SSH_KEY_ENV = "MCTA_SERVER_SSH_KEY"
# -D/--dept 的端口对（远端:本地）；后台子进程通过环境变量继承。
SOCKS_PORTS_ENV = "MCTA_SERVER_SOCKS_PORTS"
DEFAULT_SOCKS_PORT = 9069
# 传输通道数（默认3）：传输通道1/2 大小文件都能走，第三条及以后只传小文件。
# 大于该阈值的传输视为“大”；调度器每次传输都按大小与当前负载重新选通道。
XFER_CHANNELS_COUNT = min(16, max(2, int(
    os.environ.get("MCTA_XFER_CHANNELS", "3") or 3)))
XFER_LARGE_BYTES = max(
    0, int(os.environ.get("MCTA_XFER_LARGE_MB", "4") or 4)) * 1024 * 1024
XFER_CHANNELS = tuple("xfer%d" % i for i in range(1, XFER_CHANNELS_COUNT + 1))
XFER_LARGE_CAPABLE = XFER_CHANNELS[:2]  # 传输通道1/2：大小文件通用
XFER_SMALL_ONLY = XFER_CHANNELS[2:]     # 传输通道3及以后：只允许小文件


class RemoteError(Exception):
    """SSH/SFTP 连接或路径错误。"""


class RemoteNotFound(RemoteError):
    """远端文件或目录不存在（SFTP 返回 ENOENT）。"""

    not_found = True


class PasswordRequired(RemoteError):
    """本地密钥/agent 都不可用，需要交互式密码。"""


DEFAULT_RENDER_SOCKET = "~/.config/mcta/sock/mcta.sock"
# -c/--socket 与 -R --socket 共用的默认路径，可用 MCTA_REMOTE_SOCKET 覆盖。
DEFAULT_FORWARD_SOCKET = DEFAULT_RENDER_SOCKET
REMOTE_RENDER_RETRY_SECONDS = max(
    1.0, float(os.environ.get("MCTA_RENDER_RETRY_SECONDS", "30") or 30))

# 文件正文缓存：放在 ~/.cache/mcta 下，按服务器固定目录名，退出不删除以便复用。
CACHE_WARN_BYTES = 2 * 1024 * 1024 * 1024  # 超过 2 GB 才提示（不强制清理）


def cache_base_dir():
    """与 3D 渲染缓存共用的根目录，默认 ~/.cache/mcta。"""
    return Path(os.environ.get("XDG_CACHE_HOME")
                or str(Path.home() / ".cache")) / "mcta"


def cache_root_for(spec):
    """按 user@host:port 生成固定目录名，同一服务器总是使用同一份缓存。"""
    digest = hashlib.sha1(spec["spec"].encode("utf-8")).hexdigest()[:12]
    root = cache_base_dir() / ("ssh-" + digest)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def cache_size_warning():
    """缓存根目录超过阈值时返回提示文本，否则返回 None。"""
    base = cache_base_dir()
    if not base.is_dir():
        return None
    total = 0
    for dirpath, _dirs, files in os.walk(str(base)):
        for name in files:
            try:
                total += os.stat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    if total <= CACHE_WARN_BYTES:
        return None
    return ("缓存目录 %s 已占用 %.1f GB，可手动删除不再需要的缓存目录。"
            % (base, total / float(1024 ** 3)))


def remote_log(event, **fields):
    """关键节点的结构化 INFO 日志（stderr，不写文件、不带 token/密码）。"""
    parts = ["event=%s" % event]
    for key, value in fields.items():
        parts.append("%s=%s" % (key, value))
    print("[remote] " + " ".join(parts), file=sys.stderr, flush=True)


_RENDER_CHANNELS = weakref.WeakSet()


def _cleanup_render_channels():
    for channel in list(_RENDER_CHANNELS):
        try:
            channel.close()
        except Exception:
            pass


atexit.register(_cleanup_render_channels)


_LEGACY_SETUP = False
_LEGACY_LOCK = threading.Lock()

# paramiko 5 删除了旧版 SHA-1 算法；这里补回，等价 OpenSSH 的
# -oKexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group1-sha1
# -oHostKeyAlgorithms=+ssh-rsa。只在本进程注册，不改动系统配置。
_GROUP1_P = 0xFFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7EDEE386BFB5A899FA5AE9F24117C4B1FE649286651ECE65381FFFFFFFFFFFFFFFF


def _enable_legacy_algorithms():
    global _LEGACY_SETUP
    if _LEGACY_SETUP or paramiko is None:
        return
    with _LEGACY_LOCK:
        if _LEGACY_SETUP:
            return
        transport_cls = getattr(paramiko, "Transport", None)
        if transport_cls is None:
            return
        try:
            from hashlib import sha1
            # paramiko 3/5 都保留了这个类；3.x 里它继承自 SHA-1 实现，
            # 5.x 里它是完整实现，两者都可直接派生出旧算法。
            from paramiko.kex_group14 import KexGroup14SHA256 as _KexBase
        except Exception:
            _KexBase = None
        if _KexBase is not None:
            kex_info = transport_cls._kex_info
            preferred = list(getattr(transport_cls, "_preferred_kex", ()))
            name14 = "diffie-hellman-group14-sha1"
            if name14 not in kex_info:
                class KexGroup14SHA1(_KexBase):
                    name = name14
                    hash_algo = sha1
                kex_info[name14] = KexGroup14SHA1
            if name14 not in preferred:
                preferred.append(name14)
            name1 = "diffie-hellman-group1-sha1"
            if name1 not in kex_info:
                class KexGroup1SHA1(_KexBase):
                    P = _GROUP1_P
                    G = 2
                    name = name1
                    hash_algo = sha1
                kex_info[name1] = KexGroup1SHA1
            if name1 not in preferred:
                preferred.append(name1)
            transport_cls._preferred_kex = tuple(preferred)

        rsa_cls = getattr(paramiko, "RSAKey", None)
        if rsa_cls is not None:
            try:
                from cryptography.hazmat.primitives.hashes import SHA1
                hashes = getattr(rsa_cls, "HASHES", None)
                if isinstance(hashes, dict):
                    hashes.setdefault("ssh-rsa", SHA1)
            except Exception:
                pass
            transport_cls._key_info.setdefault("ssh-rsa", rsa_cls)
            keys = list(getattr(transport_cls, "_preferred_keys", ()))
            if "ssh-rsa" not in keys:
                keys.append("ssh-rsa")
            transport_cls._preferred_keys = tuple(keys)
            pubkeys = list(getattr(transport_cls, "_preferred_pubkeys", ()))
            if "ssh-rsa" not in pubkeys:
                pubkeys.append("ssh-rsa")
            transport_cls._preferred_pubkeys = tuple(pubkeys)
        _LEGACY_SETUP = True


def _looks_port(text):
    return str(text).isdigit()


def _port_value(text):
    """把端口文本转成整数；不是数字或越界时返回 None。"""
    if not _looks_port(text):
        return None
    value = int(text)
    return value if 1 <= value <= 65535 else None


def parse_ssh_spec(parts):
    """解析 -R 输入，用户名和端口都可省略。

    支持：``user@host:22`` / ``user@host 22`` / ``user host 22`` /
    ``host 22`` / ``user host`` / ``host`` / ``[::1]:22``。
    省略用户名时用本机用户名，省略端口时用 22。
    """
    if isinstance(parts, str):
        parts = [parts]
    pieces = []
    for part in parts or []:
        pieces.extend(str(part).split())
    if not pieces or len(pieces) > 3:
        raise RemoteError(
            "SSH 参数格式应为 USER@HOST:PORT / USER@HOST PORT / USER HOST PORT；"
            "用户名和端口可省略")

    user = getpass.getuser()
    port = None
    if len(pieces) == 3:
        user, hostport, raw_port = pieces
        port = _port_value(raw_port)
        if port is None:
            raise RemoteError("SSH 端口必须是 1–65535 的数字：%s" % raw_port)
    elif len(pieces) == 2:
        first, second = pieces
        second_port = _port_value(second)
        if "@" in first:
            user, hostport = first.rsplit("@", 1)
            if second_port is None:
                raise RemoteError("SSH 端口必须是 1–65535 的数字：%s" % second)
            port = second_port
        elif second_port is not None:
            hostport, port = first, second_port
        elif _looks_port(second):
            raise RemoteError("SSH 端口必须是 1–65535 的数字：%s" % second)
        else:
            user, hostport = first, second
    else:
        hostport = pieces[0]

    if "@" in hostport:
        user, hostport = hostport.rsplit("@", 1)
    if not user:
        raise RemoteError("SSH 用户名不能为空")

    if hostport.startswith("["):
        end = hostport.find("]")
        if end < 0:
            raise RemoteError("SSH 地址格式错误：%s" % hostport)
        host = hostport[1:end]
        tail = hostport[end + 1:]
        if tail:
            if not tail.startswith(":"):
                raise RemoteError("SSH 地址格式错误：%s" % hostport)
            inline_port = _port_value(tail[1:])
            if inline_port is None:
                raise RemoteError("SSH 端口必须是 1–65535 的数字：%s" % tail[1:])
            if port is not None and port != inline_port:
                raise RemoteError("SSH 端口重复且不一致：%s 与 %s" % (port, inline_port))
            port = inline_port
    elif hostport.count(":") == 1:
        host, _, tail = hostport.partition(":")
        inline_port = _port_value(tail)
        if inline_port is None:
            raise RemoteError("SSH 端口必须是 1–65535 的数字：%s" % tail)
        if port is not None and port != inline_port:
            raise RemoteError("SSH 端口重复且不一致：%s 与 %s" % (port, inline_port))
        port = inline_port
    elif hostport.count(":") > 1:
        raise RemoteError("IPv6 地址请用方括号括起，如 [::1]:22")
    else:
        host = hostport

    if not host:
        raise RemoteError("SSH 地址不能为空")
    if port is None:
        port = 22
    if not 1 <= port <= 65535:
        raise RemoteError("SSH 端口需在 1–65535 之间")
    return {
        "user": user, "host": host, "port": port,
        "spec": "%s@%s:%d" % (user, host, port),
        "display": "%s@%s:%d" % (user, host, port),
    }


def _key_candidates():
    """本机可用的私钥：优先常见名字，再补充 ~/.ssh 下其它私钥。"""
    ssh_dir = Path.home() / ".ssh"
    names = ("id_ed25519", "id_ecdsa", "id_rsa", "id_dsa", "identity")
    paths = []
    for name in names:
        path = ssh_dir / name
        if path.is_file():
            paths.append(path)
    def is_private_key(path):
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as fh:
                return "PRIVATE KEY" in fh.readline().upper()
        except OSError:
            return False

    try:
        for path in sorted(ssh_dir.iterdir()):
            if (path.is_file() and not path.name.endswith(".pub")
                    and path not in paths and is_private_key(path)):
                paths.append(path)
    except OSError:
        pass
    return [p for p in paths if is_private_key(p)]


def identity_for(spec):
    """返回 -i 指定的私钥路径；未指定时为空串，仍走 agent/默认密钥发现。"""
    value = (spec.get("identity") if isinstance(spec, dict) else "") or \
        os.environ.get(SSH_KEY_ENV, "")
    return os.path.expanduser(str(value).strip()) if value else ""


def spec_from_env():
    """从后台进程环境恢复 SSH 目标（含 -i 指定的私钥）。"""
    raw = os.environ.get(SSH_SPEC_ENV, "").strip()
    if not raw:
        return None
    spec = parse_ssh_spec([raw])
    identity = identity_for({})
    if identity:
        spec["identity"] = identity
    return spec


def _banner_failure(exc):
    """老 sshd 限流时常在 SSH banner 阶段直接断开，短暂重试即可恢复。"""
    return isinstance(exc, EOFError) or "banner" in str(exc).lower()


def connect(spec, password=None, prompt=False, verbose=True):
    """建立 SSH 客户端：已知密码优先 → agent → 本地私钥 → 密码提示。

    预检判定需要密码后，入口会把密码传进来；此时若先枚举本机密钥，老旧
    sshd 会把连续的失败连接掐断，真正用密码的那次也会报 banner 错误。
    因此密码已知时先试密码，失败再回落密钥。``prompt=False`` 且无可用密钥
    时抛 PasswordRequired，由启动入口切到前台读取密码。
    """
    if paramiko is None:
        raise RemoteError("远程模式需要 paramiko：pip install paramiko")
    _enable_legacy_algorithms()
    # 老 sshd 拒绝连接时 paramiko 会把完整 traceback 打到 stderr；
    # 这里只保留自己的简短提示，避免启动过程刷屏。
    logging.getLogger("paramiko.transport").setLevel(logging.CRITICAL)
    kwargs = dict(hostname=spec["host"], port=spec["port"], username=spec["user"],
                  timeout=10, allow_agent=False, look_for_keys=False)
    identity = identity_for(spec)
    if identity and not Path(identity).is_file():
        raise RemoteError("指定的 SSH 私钥不存在：%s" % identity)
    key_failures = []
    password_failures = []

    def note(message):
        if verbose:
            print("[ssh] " + message, file=sys.stderr, flush=True)

    def attempt(auth):
        # 每次认证用全新客户端，避免失败连接留下的 transport 影响下一次尝试。
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(**kwargs, **auth)
        transport = client.get_transport()
        if transport is not None:
            transport.set_keepalive(30)
        return client

    def try_password(value):
        for round_no in range(2):
            try:
                return attempt({"password": value})
            except Exception as exc:  # noqa: BLE001 - 认证失败原因各异
                password_failures.append(str(exc))
                if round_no == 0 and _banner_failure(exc):
                    time.sleep(0.3)
                    continue
                return None
        return None

    if password is None and prompt:
        password = getpass.getpass("%s 的 SSH 密码（密钥认证失败）：" % spec["display"])
    if password is not None:
        client = try_password(password)
        if client is not None:
            note("使用密码认证")
            return client, "password"

    if not identity:
        try:
            agent = paramiko.Agent()
            for key in agent.get_keys():
                try:
                    client = attempt({"pkey": key})
                    note("使用 ssh-agent 密钥认证")
                    return client, "ssh-agent"
                except Exception as exc:  # noqa: BLE001
                    key_failures.append("agent: %s" % exc)
        except Exception:
            pass

    # 指定 -i 时只试这一把钥匙，避免静默回退到别的密钥掩盖配置错误。
    keys = [Path(identity)] if identity else _key_candidates()
    for path in keys:
        try:
            client = attempt({"key_filename": str(path)})
            note("使用本地私钥 %s" % path)
            return client, str(path)
        except Exception as exc:  # noqa: BLE001
            key_failures.append("%s: %s" % (path, exc))

    if password is None:
        detail = key_failures[0] if key_failures else "没有可用认证方式"
        raise PasswordRequired("密钥认证失败（%s），需要密码" % detail)
    detail = (password_failures[0] if password_failures
              else (key_failures[0] if key_failures else "没有可用认证方式"))
    raise RemoteError("SSH 连接失败：%s" % detail)


def check(spec, verbose=True, timeout=5):
    """非交互预检 SSH 服务，等价于 ssh -oBatchMode=yes -oConnectTimeout=N。

    返回 dict：``reachable``、``client``（密钥认证成功时为已连接客户端）、
    ``auth``、``password_required``、``detail``。没有可用密钥或密钥认证失败
    时由启动入口直接通过 getpass 读取密码，不写命令行、环境变量或日志。
    """
    if paramiko is None:
        raise RemoteError("远程模式需要 paramiko：pip install paramiko")
    _enable_legacy_algorithms()
    target = "%s:%d" % (spec["host"], spec["port"])
    try:
        with socket.create_connection((spec["host"], spec["port"]), timeout=timeout):
            pass
    except OSError as exc:
        raise RemoteError("无法连接 %s：%s" % (target, exc))

    try:
        client, auth = connect(spec, password=None, prompt=False, verbose=False)
    except PasswordRequired as exc:
        if verbose:
            print("[ssh] 检测：%s 可达，但密钥认证失败，需要密码" % target,
                  file=sys.stderr, flush=True)
        return {"reachable": True, "client": None, "auth": None,
                "password_required": True, "detail": str(exc)}
    except RemoteError as exc:
        detail = str(exc)
        lowered = detail.lower()
        if "kex" in lowered or "host key" in lowered or "算法" in detail:
            detail += "；请确认 -R 中写的 SSH 端口正确（不是 -p 的网页端口）"
        raise RemoteError("SSH 认证/协商失败：%s" % detail)

    if verbose:
        print("[ssh] 检测通过：%s（%s）" % (target, auth),
              file=sys.stderr, flush=True)
    return {"reachable": True, "client": client, "auth": auth,
            "password_required": False, "detail": ""}


class _SftpChannel:
    """一条独立的 SSH + SFTP 连接，带断线自动重连。

    RemoteFS 为目录浏览与每条传输通道各持有一个实例，
    彼此不共享连接：某个通道上的大文件传输不会阻塞其它通道。
    """

    def __init__(self, spec, password, prompt, verbose, client=None, auth=None):
        self.spec = spec
        # 密码只留在服务进程内存中用于自动重连；不写环境变量、命令行或日志。
        self._password = password
        if client is None:
            self.client, self.auth = connect(spec, password=password,
                                             prompt=prompt, verbose=verbose)
        else:
            # 复用启动时预检建立的 SSH 连接，避免重复握手。
            self.client, self.auth = client, auth or "prechecked"
        self.sftp = self.client.open_sftp()
        self._closing = False
        self._reconnect_lock = threading.RLock()
        self._call_lock = threading.RLock()

    def call(self, name, *args):
        """调用 SFTP；同一通道串行，断线时只重连本通道并重试一次。"""
        with self._call_lock:
            def do():
                return getattr(self.sftp, name)(*args)
            try:
                return do()
            except Exception as exc:
                if self._closing or not RemoteFS._is_conn_error(exc):
                    raise
                self.reconnect()
                return do()

    def reconnect(self):
        with self._reconnect_lock:
            if self._closing:
                raise RemoteError("远程服务正在关闭")
            print("[ssh] 文件通道连接已断开，正在重连 %s…" % self.spec["display"],
                  file=sys.stderr, flush=True)
            try:
                self.sftp.close()
            except Exception:
                pass
            try:
                self.client.close()
            except Exception:
                pass
            try:
                client, auth = connect(self.spec, password=self._password,
                                       prompt=False, verbose=False)
                self.client, self.auth = client, auth
                self.sftp = client.open_sftp()
            except PasswordRequired as exc:
                raise RemoteError("SSH 连接断开，自动重连需要密码但不可交互：%s" % exc)

    def close(self):
        self._closing = True
        try:
            self.sftp.close()
        except Exception:
            pass
        try:
            self.client.close()
        except Exception:
            pass


class RemoteFS:
    """SFTP 文件操作 + 本地临时缓存，分成一条浏览通道和多条传输通道。

    browse / xfer1 / xfer2 / ... 各自持有独立的 SSH + SFTP 连接
    （``_SftpChannel``）；传输通道1/2 大小文件通用，第三条及以后只传小文件。
    它们与终端的 RemoteSSH 互不阻塞。远程绝对路径会镜像到
    ``cache_root`` 下（去掉开头的 '/'），所以 ``..`` 只会在缓存目录内移动。
    """

    def __init__(self, spec, password=None, prompt=False, verbose=True,
                 client=None, auth=None):
        self.spec = spec
        self._password = password
        # 浏览通道 + 每条传输通道各自独立；预检连接只复用给浏览通道。
        # 传输通道默认 3 条：1/2 大小文件通用，3 及以后只传小文件；
        # 每次传输按文件大小与实时负载选通道，可在并发中随时切换。
        self.channels = {
            "browse": _SftpChannel(spec, password, prompt, verbose,
                                   client=client, auth=auth),
        }
        for name in XFER_CHANNELS:
            self.channels[name] = _SftpChannel(spec, password, False, verbose)
        # 兼容属性：client/sftp/auth 指向浏览通道，供终端 rc 写入等旧调用使用。
        self.client = self.channels["browse"].client
        self.sftp = self.channels["browse"].sftp
        self.auth = self.channels["browse"].auth
        self.cache_root = cache_root_for(spec)
        # 按通道分锁：浏览独立；各传输通道内部串行，调度器负责分流。
        self._locks = {name: threading.RLock() for name in self.channels}
        # 传输负载：每条通道进行中的传输次数，以及其中大文件的次数。
        self._xfer_load = {name: 0 for name in XFER_CHANNELS}
        self._xfer_big = {name: 0 for name in XFER_CHANNELS}
        self._xfer_guard = threading.Lock()
        self._closing = False
        self._terminals = weakref.WeakSet()
        # 第五通道（3D 渲染）状态：None=未探测，False=不可用，tuple=(命令, 版本)。
        self._remote_server = None
        self._render_channel = None
        self._remote_home = ""
        self._render_error = ""
        self._render_socket = ""
        self._render_fail_at = 0.0
        # 目录列表短缓存：同一会话内反复刷新同一目录不必每次走 SFTP。
        self._list_cache = {}
        self._list_ttl = max(
            0.0, float(os.environ.get("MCTA_REMOTE_LIST_TTL", "1") or 0))
        try:
            self.default_root = posixpath.normpath(
                self.channels["browse"].call("normalize", ".") or "/")
        except Exception:
            self.default_root = "/"
        self.root = self.default_root

    @classmethod
    def from_env(cls, verbose=True):
        spec = spec_from_env()
        if spec is None:
            return None
        fs = cls(spec, prompt=False, verbose=verbose)
        wanted = os.environ.get(SSH_ROOT_ENV, "").strip()
        if wanted:
            fs.set_root(wanted)
        return fs

    def env(self):
        result = {
            SSH_SPEC_ENV: self.spec["spec"],
            SSH_ROOT_ENV: self.root,
        }
        identity = identity_for(self.spec)
        if identity:
            result[SSH_KEY_ENV] = identity
        return result

    @staticmethod
    def _is_conn_error(exc):
        """判断是否为可重试的 SSH/SFTP 断连错误。"""
        if isinstance(exc, (EOFError, BrokenPipeError, ConnectionResetError,
                            ConnectionAbortedError, socket.timeout)):
            return True
        ssh_exc = getattr(paramiko, "SSHException", None)
        if ssh_exc is not None and isinstance(exc, ssh_exc):
            return True
        text = str(exc).lower()
        markers = ("broken pipe", "connection reset", "connection closed",
                   "socket is closed", "transport is closing", "eof",
                   "timed out", "no such channel", "channel closed",
                   "server unexpectedly closed")
        return any(marker in text for marker in markers)

    def _pick_xfer(self, size=0):
        """为本次传输选通道：大文件只用传输通道1/2，小文件可用全部通道。

        每次调用都按当前负载重新选择，因此并发上传/下载会随时切换通道：
        - 大文件（>= XFER_LARGE_BYTES）：在通用通道中优先空闲的一条，
          否则选负载最低的，不会进入小文件专用通道。
        - 小文件：优先没有大文件占用、负载最低的通道；负载相同时优先
          小文件专用通道，把通用通道留给大文件。
        返回 (channel_name, end_cb)，传输结束后必须调用 end_cb() 释放负载。
        """
        with self._xfer_guard:
            big = size >= XFER_LARGE_BYTES
            candidates = XFER_LARGE_CAPABLE if big else XFER_CHANNELS
            if big:
                idle = [n for n in candidates if self._xfer_load[n] == 0]
                name = idle[0] if idle else min(
                    candidates, key=lambda n: (self._xfer_load[n], n))
            else:
                name = min(candidates, key=lambda n: (
                    self._xfer_big[n], self._xfer_load[n],
                    n not in XFER_SMALL_ONLY, n))
            self._xfer_load[name] += 1
            if big:
                self._xfer_big[name] += 1

        def end():
            with self._xfer_guard:
                if self._xfer_load[name] > 0:
                    self._xfer_load[name] -= 1
                if big and self._xfer_big[name] > 0:
                    self._xfer_big[name] -= 1

        return name, end

    def _sftp_call(self, name, *args, channel="browse"):
        """在指定通道上调用 SFTP；断线时只重连该通道并重试一次。

        channel: browse=目录浏览 / xfer1、xfer2、xfer3…=传输通道，
        每条都能上传或下载，具体由 _pick_xfer 按大小与负载选择。
        ENOENT 统一包装成 RemoteNotFound，交给路由层返回 404，避免未捕获
        异常冒泡到 socketserver 刷出整段 traceback。
        """
        try:
            return self.channels[channel].call(name, *args)
        except OSError as exc:
            if getattr(exc, "errno", None) == errno.ENOENT:
                raise RemoteNotFound("文件不存在：%s" % (args[0] if args else "")) from exc
            raise

    def _reconnect(self):
        """重连全部文件通道（终端由 RemoteSSH 自行重连）。"""
        if self._closing:
            raise RemoteError("远程服务正在关闭")
        # 连接重建后必须重新探测远端 mt.server；旧隧道绑定在旧 SSH 上。
        self._remote_server = None
        self._render_fail_at = 0.0
        if self._render_channel is not None:
            self._render_channel.close()
            self._render_channel = None
        for ch in self.channels.values():
            try:
                ch.reconnect()
            except Exception:
                pass
        # 浏览通道重连后刷新默认目录，并同步兼容属性。
        browse = self.channels["browse"]
        self.client, self.auth, self.sftp = browse.client, browse.auth, browse.sftp
        try:
            self.default_root = posixpath.normpath(
                browse.call("normalize", ".") or "/")
        except Exception:
            pass

    def close(self):
        self._closing = True
        if self._render_channel is not None:
            self._render_channel.close()
            self._render_channel = None
        for ch in self.channels.values():
            ch.close()

    def set_root(self, path, strict=False):
        """把 -d 解释为远程路径；无效时回退到 SSH 默认目录。"""
        if not path:
            return False
        try:
            target = self.remote_for(path)
            info = self._sftp_call("stat", target)
            if not stat.S_ISDIR(info.st_mode):
                raise RemoteError("不是目录")
        except Exception as exc:
            if strict:
                raise RemoteError("远程目录 %s 不可用：%s" % (path, exc))
            return False
        self.root = posixpath.normpath(target)
        return True

    @property
    def root_local(self):
        return self.local_for_remote(self.root)

    @property
    def display(self):
        return self.spec["display"]

    def stat_remote(self, remote):
        """读取远端 stat；断线时自动重连重试。"""
        return self._sftp_call("stat", remote)

    def _exec_remote(self, command, timeout=5):
        """在浏览通道的 SSH 连接上执行只读命令，返回 stdout 文本。"""
        client = self.channels["browse"].client
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        channel = getattr(stdout, "channel", None)
        if channel is not None:
            channel.settimeout(timeout)
        try:
            return stdout.read().decode("utf-8", "replace")
        finally:
            try:
                stderr.read()
            except Exception:
                pass

    def remote_home(self):
        """缓存远端 HOME，用于展开 socket 路径中的 ~。"""
        if self._remote_home:
            return self._remote_home
        try:
            value = self._exec_remote('printf "%s" "$HOME"').strip()
        except Exception:
            value = ""
        self._remote_home = value or "/"
        return self._remote_home

    def detect_remote_server(self):
        """只检查远端 mt.server 可执行文件路径；结果按实例缓存。

        非交互 SSH 的 PATH 往往不含 ~/.local/bin（pip --user / conda 软链），
        因此除 command -v 外还显式搜索常见安装位置。版本一致性由用户统一安装保证，
        这里不再执行 -V / -h 探活；找不到也不要报错抛异常。
        """
        if self._remote_server is not None:
            return self._remote_server
        started = time.monotonic()
        self._remote_server = False
        self._render_error = ""
        probe = r"""
# 有些系统自带 GNU mt（磁带工具），command -v mt 会误命中；用 -V 输出核实。
for c in "$(command -v mt.server 2>/dev/null)" "$(command -v mt 2>/dev/null)" \
         "$HOME/.local/bin/mt.server" "$HOME/.local/bin/mt"; do
  if [ -n "$c" ] && [ -x "$c" ]; then
    case "$("$c" -V 2>/dev/null)" in
      *McTa*|*mcta*|*"Meta Crystal"*) printf '%s\n' "$c"; break ;;
    esac
  fi
done
for p in python3 "$HOME/.local/miniconda3/envs/"*/bin/python \
         "$HOME/.local/anaconda3/envs/"*/bin/python \
         "$HOME/.local/mambaforge/envs/"*/bin/python \
         "$HOME/soft/miniconda3/envs/"*/bin/python \
         "$HOME/miniconda3/envs/"*/bin/python \
         "$HOME/anaconda3/envs/"*/bin/python \
         "$HOME/mambaforge/envs/"*/bin/python /opt/conda/bin/python; do
  if [ -n "$p" ] && [ -x "$p" ] && "$p" -c 'import mcta' >/dev/null 2>&1; then
    printf 'python:%s\n' "$p"; break
  fi
done
"""
        try:
            lines = [x.strip() for x in
                     self._exec_remote(probe, timeout=10).splitlines() if x.strip()]
            found = lines[0] if lines else ""
            cmd = []
            if found.startswith("python:"):
                cmd = [found[len("python:"):], "-m", "mcta", "server"]
            elif found:
                cmd = [found]
                if posixpath.basename(found) == "mt":
                    cmd.append("server")
            if not cmd:
                self._render_error = "远端未找到 mt.server（已搜索 PATH / ~/.local/bin / conda）"
                remote_log("remote_server_detect", host=self.display,
                           result="not-installed",
                           elapsed_ms=int((time.monotonic() - started) * 1000))
                return False
            self._remote_server = (cmd, "")
            remote_log("remote_server_detect", host=self.display, result="ok",
                       command=shlex.join(cmd),
                       elapsed_ms=int((time.monotonic() - started) * 1000))
        except Exception as exc:  # noqa: BLE001 - 远端问题一律回退
            self._render_error = "远端探测失败：%s" % str(exc)[:80]
            remote_log("remote_server_detect", host=self.display, result="error",
                       detail=str(exc)[:120],
                       elapsed_ms=int((time.monotonic() - started) * 1000))
        return self._remote_server

    def start_render_channel(self, socket_path=None):
        """按需建立隧道；失败后做负缓存，避免每次渲染请求都重试 30 秒。"""
        if socket_path:
            self._render_socket = socket_path
        socket_path = self._render_socket or DEFAULT_RENDER_SOCKET
        if self._closing:
            self._render_error = "远程连接正在关闭"
            return None
        if self._render_channel is not None:
            if self.render_channel_ready():
                return self._render_channel
            # ssh 进程已退出：立即关掉旧隧道重建，不落入失败负缓存。
            self._render_channel.close()
            self._render_channel = None
        now = time.monotonic()
        if self._render_fail_at and now - self._render_fail_at < REMOTE_RENDER_RETRY_SECONDS:
            if "负缓存" not in self._render_error:
                self._render_error = ((self._render_error or "远端渲染通道暂不可用")
                                      + "（负缓存）")
            remote_log("remote_render", host=self.display, result="negative-cache",
                       retry_in=int(REMOTE_RENDER_RETRY_SECONDS - (now - self._render_fail_at)))
            return None
        info = self.detect_remote_server()
        if not info:
            self._render_error = self._render_error or "远端未找到 mt.server"
            self._render_fail_at = now
            return None
        cmd, _version = info
        channel = RemoteRenderChannel(self.spec, socket_path,
                                      cmd, password=self._password,
                                      home=self.remote_home())
        if channel.start():
            self._render_error = ""
            self._render_fail_at = 0.0
            self._render_channel = channel
            return channel
        self._render_error = getattr(channel, "error", "") or "SSH 隧道建立失败"
        self._render_fail_at = time.monotonic()
        return None

    def render_channel_ready(self, channel=None):
        """渲染通道是否可用：除了就绪标志，还要确认 ssh 进程仍存活。"""
        channel = channel if channel is not None else self._render_channel
        if channel is None or not getattr(channel, "ready", False):
            return False
        proc = getattr(channel, "proc", None)
        return proc is None or proc.poll() is None

    def mark_render_request_failure(self, reason=""):
        """单文件/单次请求失败：只记日志，不关闭隧道、不设全局负缓存。"""
        remote_log("remote_render", host=self.display,
                   result="request-failure", detail=str(reason)[:120])

    def mark_render_failure(self, reason=""):
        """远端渲染通道级失败时关闭通道并进入负缓存，定期再试。"""
        self._render_fail_at = time.monotonic()
        self._render_error = reason or self._render_error or "远端渲染请求失败"
        channel = self._render_channel
        self._render_channel = None
        if channel is not None:
            try:
                channel.close()
            except Exception:
                pass
        remote_log("remote_render", host=self.display, result="negative-cache-set",
                   detail=str(self._render_error)[:120])

    def open_remote(self, remote, mode="rb", size=0):
        """打开远端文件句柄；调用方负责关闭，不经过本地缓存。

        音视频 Range 流式播放与批量 ZIP 下载按已知文件大小走合适的传输通道，
        与目录浏览互不阻塞；长连接期间占用该通道的负载计数直到句柄关闭。
        """
        name, end = self._pick_xfer(size)
        try:
            return _TrackedHandle(
                self._sftp_call("open", remote, mode, channel=name), end)
        except Exception:
            end()
            raise

    def is_conn_error(self, exc):
        return self._is_conn_error(exc)

    def reconnect(self):
        self._reconnect()

    def remote_for(self, rel):
        raw = str(rel or "").replace("\\", "/").strip()
        if not raw or raw == ".":
            return self.root
        if raw.startswith("/"):
            return posixpath.normpath(raw)
        return posixpath.normpath(posixpath.join(self.root, raw))

    def rel(self, remote):
        value = posixpath.relpath(posixpath.normpath(remote), self.root)
        return "" if value == "." else value

    def current_rel(self, rel):
        return self.rel(self.remote_for(rel))

    def parent_rel(self, rel):
        remote = self.remote_for(rel)
        if posixpath.normpath(remote) == self.root:
            return ""
        return self.rel(posixpath.dirname(remote))

    def current_remote(self, rel):
        """页面展示与终端同步使用的远程绝对路径。"""
        return self.remote_for(rel)

    def parent_remote(self, rel):
        """远程父目录；起始目录自身返回空字符串，与本地模式一致。"""
        remote = self.remote_for(rel)
        if posixpath.normpath(remote) == self.root:
            return ""
        return posixpath.dirname(remote)

    def local_for_remote(self, remote):
        parts = [p for p in posixpath.normpath(remote).split("/") if p]
        return self.cache_root.joinpath(*parts)

    def local_for_rel(self, rel):
        return self.local_for_remote(self.remote_for(rel))

    def remote_for_local(self, local):
        """把本地缓存路径反解成远程绝对路径（页面回传路径时使用）。"""
        path = Path(local).resolve()
        try:
            parts = path.relative_to(self.cache_root.resolve()).parts
        except ValueError:
            return self.root
        return posixpath.normpath("/" + "/".join(parts))

    def _need_download(self, local, info):
        if not local.is_file():
            return True
        try:
            local_stat = local.stat()
        except OSError:
            return True
        if local_stat.st_size != info.st_size:
            return True
        remote_mtime = int(getattr(info, "st_mtime", 0) or 0)
        if remote_mtime and abs(int(local_stat.st_mtime) - remote_mtime) > 1:
            return True
        return False

    def _local_lock(self, local):
        """按本地目标路径返回一把锁，避免并发请求重复下载同一文件。"""
        key = str(local)
        with self._xfer_guard:
            lock = getattr(self, "_local_locks", None)
            if lock is None:
                lock = self._local_locks = {}
            if key not in lock:
                lock[key] = threading.RLock()
            return lock[key]

    def _do_download(self, remote, info, local, channel):
        """在指定传输通道上把远端文件拉到本地缓存路径。"""
        tmp = local.with_name(local.name + ".mcta-part")

        def download():
            with self._sftp_call("open", remote, "rb", channel=channel) as src, tmp.open("wb") as dst:
                shutil.copyfileobj(src, dst, 64 * 1024)

        try:
            download()
        except Exception as exc:
            if self._closing or not self._is_conn_error(exc):
                raise
            self._reconnect()
            download()
        try:
            os.replace(str(tmp), str(local))
            remote_mtime = int(getattr(info, "st_mtime", 0) or 0)
            if remote_mtime:
                os.utime(str(local), (remote_mtime, remote_mtime))
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
        return local

    def ensure_stat(self, remote, info):
        """按已取得的 stat 结果返回本地缓存路径，避免重复 stat。

        批量下载已经对文件做过 stat，可直接复用；只有 size/mtime 不一致
        时才重新通过传输通道拉取，和预览走同一份本地缓存。
        """
        local = self.local_for_remote(remote)
        if stat.S_ISDIR(getattr(info, "st_mode", 0)):
            local.mkdir(parents=True, exist_ok=True)
            return local
        local.parent.mkdir(parents=True, exist_ok=True)
        if not self._need_download(local, info):
            return local
        # 同一本地文件只下载一次：按目标路径加锁，避免两个请求并发写同一临时文件。
        with self._local_lock(local):
            if not self._need_download(local, info):
                return local
            size = int(getattr(info, "st_size", 0) or 0)
            channel, end = self._pick_xfer(size)
            try:
                with self._locks[channel]:
                    local = self._do_download(remote, info, local, channel)
            finally:
                end()
            return local

    def ensure(self, rel):
        """返回 rel 对应的本地缓存路径；文件不存在或过期时通过 SFTP 下载。"""
        remote = self.remote_for(rel)
        channel, end = self._pick_xfer(0)
        try:
            info = self._sftp_call("stat", remote, channel=channel)
        finally:
            end()
        return self.ensure_stat(remote, info)

    def ensure_remote(self, remote):
        """按远程绝对路径取本地缓存（term cwd 使用）。"""
        return self.ensure(remote)

    def invalidate_list_cache(self, remote=None):
        """写操作后失效目录列表缓存；remote 为文件则失效其父目录。"""
        with self._locks["browse"]:
            if not remote:
                self._list_cache.clear()
                return
            norm = posixpath.normpath(remote)
            parent = posixpath.dirname(norm) or "/"
            for key in list(self._list_cache):
                if key == norm or key == parent or key.startswith(norm + "/"):
                    self._list_cache.pop(key, None)

    def list_entries(self, rel):
        """列出目录；短 TTL 命中时直接返回，写操作会主动失效。"""
        with self._locks["browse"]:
            remote = self.remote_for(rel)
            now = time.monotonic()
            cached = self._list_cache.get(remote)
            if (self._list_ttl > 0 and cached
                    and now - cached[0] < self._list_ttl):
                return [dict(row) for row in cached[1]]
            info = self._sftp_call("stat", remote)
            if not stat.S_ISDIR(info.st_mode):
                raise RemoteError("不是目录")
            rows = []
            for attr in self._sftp_call("listdir_attr", remote):
                name = attr.filename
                child = posixpath.join(remote, name)
                is_dir = bool(getattr(attr, "st_mode", 0) and stat.S_ISDIR(attr.st_mode))
                if is_dir:
                    self.local_for_remote(child).mkdir(parents=True, exist_ok=True)
                mtime = int(getattr(attr, "st_mtime", 0) or 0)
                rows.append({
                    "name": name,
                    # 前端所有导航、查看和终端 cd 都使用远程绝对路径。
                    "path": child,
                    "dir": is_dir,
                    "size": None if is_dir else int(getattr(attr, "st_size", 0) or 0),
                    "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)) if mtime else "",
                    "ts": mtime,
                })
            self._list_cache[remote] = (now, [dict(row) for row in rows])
            return rows

    def upload(self, remote, data):
        """写入远程文件（覆盖同名文件）；按数据大小选择较空的传输通道。"""
        size = len(data) if data is not None else 0
        channel, end = self._pick_xfer(size)
        try:
            with self._locks[channel]:
                parent = posixpath.dirname(posixpath.normpath(remote)) or "/"
                self.makedirs(parent, channel=channel)
                # call() 已在断线时自动重连该通道并重试一次。
                with self._sftp_call("open", remote, "wb", channel=channel) as dst:
                    dst.write(data)
                self.invalidate_list_cache(
                    posixpath.dirname(posixpath.normpath(remote)) or "/")
        finally:
            end()

    def makedirs(self, remote, channel="xfer1"):
        """递归创建远程目录；走指定传输通道；已存在且为目录时直接返回。"""
        cur = ""
        for part in [p for p in posixpath.normpath(remote).split("/") if p]:
            cur += "/" + part
            try:
                info = self._sftp_call("stat", cur, channel=channel)
            except FileNotFoundError:
                self._sftp_call("mkdir", cur, channel=channel)
            except Exception as exc:
                if "no such file" in str(exc).lower() or "not found" in str(exc).lower():
                    self._sftp_call("mkdir", cur, channel=channel)
                else:
                    raise
            else:
                if not stat.S_ISDIR(info.st_mode):
                    raise RemoteError("远程路径不是目录：%s" % cur)
        norm = posixpath.normpath(remote)
        self.invalidate_list_cache(posixpath.dirname(norm) or "/")
        self.invalidate_list_cache(norm)


class _TrackedHandle:
    """代理 SFTP 文件句柄，close() 时归还传输通道的负载计数。"""

    def __init__(self, handle, end_cb):
        self._handle = handle
        self._end = end_cb
        self._closed = False

    def __getattr__(self, name):
        return getattr(self._handle, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._handle.close()
        finally:
            self._end()


class RemoteRenderChannel:
    """第五条通道：本地回环 TCP 端口 → 远端 Unix socket。

    远端 mt.server 只监听 Unix socket，不监听 TCP 端口；隧道使用系统 ssh，
    远端命令以 exec 前台运行，ssh 退出时远端进程随之结束，不留孤儿进程。
    """

    def __init__(self, spec, socket_path, server_cmd, password=None, home="/", verbose=True):
        self.spec = spec
        self.socket_path = socket_path or DEFAULT_RENDER_SOCKET
        self.server_cmd = list(server_cmd)
        self.password = password
        self.home = home or "/"
        self.verbose = verbose
        self.identity = identity_for(spec)
        self.port = self._free_port()
        self.proc = None
        self.ready = False
        self.error = ""
        self._closed = False
        self._log_fd = None
        self._askpass_path = None
        _RENDER_CHANNELS.add(self)

    @staticmethod
    def _free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    @property
    def remote_socket(self):
        path = self.socket_path
        if path.startswith("~/"):
            return posixpath.normpath(posixpath.join(self.home, path[2:]))
        if path.startswith("~"):
            return posixpath.normpath(posixpath.join(self.home, path[1:].lstrip("/")))
        if path.startswith("/"):
            return posixpath.normpath(path)
        return posixpath.normpath(posixpath.join(self.home, path))

    def _make_askpass(self):
        """创建最小 askpass 助手；密码只经环境变量传递，不写进脚本内容。"""
        fd, path = tempfile.mkstemp(prefix="mcta-askpass-", suffix=".sh")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nprintf '%s' \"$MCTA_ASKPASS_SECRET\"\n")
        os.chmod(path, 0o700)
        self._askpass_path = path
        return path

    def _command(self):
        """构造 ssh 命令；返回 (argv, env)。密码只放进环境变量，不进命令行。"""
        sock = self.remote_socket
        directory = posixpath.dirname(sock)
        server = " ".join(shlex.quote(str(x)) for x in self.server_cmd)
        setup = ("mkdir -p %s && (chmod 700 %s 2>/dev/null || true)"
                 % (shlex.quote(directory), shlex.quote(directory)))
        run = ("%s --socket %s --no-token -f -Y -d /"
               % (server, shlex.quote(sock)))
        # 远端 mt.server 不读 stdin；SSH 会话断开时不会自己感知。用一层
        # wrapper 监控 stdin，会话一断就 kill 子进程，避免占用默认 socket，
        # 导致下次 -R 启动时渲染通道因“socket 正在使用”而回退本地。
        # 注意 server 必须单独后台启动，$! 才是 mt.server 本体；否则 kill
        # 只杀掉包含 mkdir/chmod 的后台子 shell，真正的服务会变孤儿。
        inner = ("%s; %s & __mcta_pid=$!; "
                 "trap 'kill $__mcta_pid 2>/dev/null' HUP INT TERM EXIT; "
                 "while IFS= read -r __mcta_line; do :; done; "
                 "kill $__mcta_pid 2>/dev/null; wait $__mcta_pid 2>/dev/null"
                 % (setup, run))
        # 用 += 追加旧算法：新服务端仍优先现代算法；有些老 sshd 只提供 SHA1 KEX。
        opts = [
            "KexAlgorithms=+diffie-hellman-group14-sha1",
            "HostKeyAlgorithms=+ssh-rsa",
            "ServerAliveInterval=30",
            "ExitOnForwardFailure=no",
            "ConnectTimeout=8",
            "StrictHostKeyChecking=accept-new",
        ]
        if self.identity:
            # OpenSSH 8.8+ 默认禁用 ssh-rsa 签名；老服务器只认它时显式追加。
            opts.append("PubkeyAcceptedKeyTypes=+ssh-rsa")
        env = None
        if self.password:
            # BatchMode=yes 会禁用密码认证；sshpass 又不是系统标配。
            # 用 OpenSSH 自带 SSH_ASKPASS（9.6 支持 SSH_ASKPASS_REQUIRE=force）。
            opts += [
                "BatchMode=no",
                "PreferredAuthentications=password,keyboard-interactive",
                "PubkeyAuthentication=no",
                "NumberOfPasswordPrompts=1",
            ]
            env = dict(os.environ,
                       SSH_ASKPASS=self._make_askpass(),
                       SSH_ASKPASS_REQUIRE="force",
                       DISPLAY=os.environ.get("DISPLAY") or ":0",
                       MCTA_ASKPASS_SECRET=self.password)
        else:
            opts.append("BatchMode=yes")
        # 不分配 PTY：远端 mt.server 的日志走 stderr/文件，
        # PTY 缓冲区写满会反过来堵住 -L 转发的渲染流量。
        argv = ["ssh", "-T"]
        if self.identity:
            argv += ["-i", self.identity]
        for opt in opts:
            argv += ["-o", opt]
        argv += ["-L", "127.0.0.1:%d:%s" % (self.port, sock),
                 "-p", str(self.spec["port"]), "-l", self.spec["user"],
                 self.spec["host"], inner]
        return argv, env

    def start(self):
        started = time.monotonic()
        if shutil.which("ssh") is None:
            self.error = "本机缺少 ssh 命令"
            remote_log("remote_tunnel", host=self.spec["display"],
                       result="no-ssh", detail="system ssh not found")
            return False
        argv, env = self._command()
        if not argv:
            return False
        log_path = Path(tempfile.gettempdir()) / ("mcta-render-ssh-%d-%d.log" % (os.getpid(), self.port))
        try:
            fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            self._log_fd = os.fdopen(fd, "wb", closefd=True)
        except OSError:
            self._log_fd = subprocess.DEVNULL
        try:
            # stdin 必须保持打开：远端 wrapper 用它判断本地会话是否还在，
            # DEVNULL 会让 wrapper 立刻读到 EOF 并关掉刚启动的 mt.server。
            self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE,
                                         stdout=self._log_fd,
                                         stderr=subprocess.STDOUT, env=env)
        except OSError as exc:
            self.error = "ssh 进程启动失败：%s" % str(exc)[:80]
            remote_log("remote_tunnel", host=self.spec["display"], result="spawn-error",
                       detail=str(exc)[:120])
            self.close()
            return False
        # 只做 TCP connect 会在远端 socket 尚未 listen 时误判就绪；
        # 这里直接经隧道取一次 /api/info，确认整条链路真的可用。
        for _ in range(50):  # 最多 10 秒，每 0.2 秒探测一次
            if self.proc.poll() is not None:
                break
            conn = None
            try:
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=1)
                conn.request("GET", "/api/info", headers={"Connection": "close"})
                resp = conn.getresponse()
                resp.read(4096)
                if resp.status == 200:
                    self.ready = True
                    remote_log("remote_tunnel", host=self.spec["display"], result="ready",
                               port=self.port, socket=self.remote_socket,
                               elapsed_ms=int((time.monotonic() - started) * 1000))
                    return True
            except Exception:  # noqa: BLE001 - 探测失败继续重试
                pass
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
            time.sleep(0.2)
        self.error = "SSH 隧道就绪超时（远端 mt.server 未起来或认证失败）"
        remote_log("remote_tunnel", host=self.spec["display"], result="timeout",
                   port=self.port, elapsed_ms=int((time.monotonic() - started) * 1000))
        self.close()
        return False

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.ready = False
        proc = self.proc
        if proc is not None:
            stdin = getattr(proc, "stdin", None)
            if stdin is not None and not stdin.closed:
                try:
                    stdin.close()
                except OSError:
                    pass
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        if self._log_fd is not None and self._log_fd is not subprocess.DEVNULL:
            try:
                self._log_fd.close()
            except OSError:
                pass
        self._log_fd = None
        if self._askpass_path:
            try:
                os.unlink(self._askpass_path)
            except FileNotFoundError:
                pass
            self._askpass_path = None
        remote_log("remote_tunnel_closed", host=self.spec["display"], port=self.port)


class SocksShare:
    """用 SSH 自带的 SOCKS5 把本机网络共享给远端。

    本机 `ssh -D` 在 127.0.0.1:<local_port> 开 SOCKS5（出口是本机网络），
    再用 `ssh -R` 把这个端口反向转发到远端 127.0.0.1:<remote_port>。
    两条 SSH 连接都由本对象持有，服务退出时一并关闭，不在远端留下常驻进程。
    """

    def __init__(self, spec, remote_port, local_port, password=None,
                 client=None, verbose=True):
        self.spec = spec
        self.remote_port = int(remote_port)
        self.local_port = int(local_port)
        self.password = password
        self.client = client
        self.verbose = verbose
        self.identity = identity_for(spec)
        self.error = ""
        self.ready = False
        self._procs = []
        self._logs = []
        self._askpass_path = None
        self._closed = False
        _RENDER_CHANNELS.add(self)

    @staticmethod
    def _socks_ready(port):
        try:
            with socket.create_connection(("127.0.0.1", port), 0.5) as sock:
                sock.settimeout(0.5)
                sock.sendall(b"\x05\x01\x00")
                return sock.recv(2) == b"\x05\x00"
        except OSError:
            return False

    def _make_askpass(self):
        fd, path = tempfile.mkstemp(prefix="mcta-askpass-", suffix=".sh")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nprintf '%s' \"$MCTA_ASKPASS_SECRET\"\n")
        os.chmod(path, 0o700)
        self._askpass_path = path
        return path

    def _spawn(self, argv, env, tag, port):
        log_path = Path(tempfile.gettempdir()) / (
            "mcta-socks-%s-%d-%d.log" % (tag, os.getpid(), port))
        try:
            fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            log = os.fdopen(fd, "wb", closefd=True)
        except OSError:
            log = subprocess.DEVNULL
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE,
                                stdout=log, stderr=subprocess.STDOUT, env=env)
        self._procs.append(proc)
        if log is not subprocess.DEVNULL:
            self._logs.append(log)
        return proc

    def _local_command(self):
        opts = [
            "ServerAliveInterval=30",
            "ExitOnForwardFailure=yes",
            "ConnectTimeout=8",
            "StrictHostKeyChecking=accept-new",
            "BatchMode=yes",
        ]
        argv = ["ssh", "-T", "-N", "-D", "127.0.0.1:%d" % self.local_port]
        for opt in opts:
            argv += ["-o", opt]
        # 本机 sshd 是 SOCKS5 的服务端，出口即本机网络；默认本机 22 端口。
        argv += ["-p", "22", "-l", getpass.getuser(), "127.0.0.1"]
        return argv, None

    def _remote_command(self):
        opts = [
            "KexAlgorithms=+diffie-hellman-group14-sha1",
            "HostKeyAlgorithms=+ssh-rsa",
            "ServerAliveInterval=30",
            "ExitOnForwardFailure=yes",
            "ConnectTimeout=8",
            "StrictHostKeyChecking=accept-new",
        ]
        if self.identity:
            opts.append("PubkeyAcceptedKeyTypes=+ssh-rsa")
        env = None
        if self.password:
            opts += [
                "BatchMode=no",
                "PreferredAuthentications=password,keyboard-interactive",
                "PubkeyAuthentication=no",
                "NumberOfPasswordPrompts=1",
            ]
            env = dict(os.environ,
                       SSH_ASKPASS=self._make_askpass(),
                       SSH_ASKPASS_REQUIRE="force",
                       DISPLAY=os.environ.get("DISPLAY") or ":0",
                       MCTA_ASKPASS_SECRET=self.password)
        else:
            opts.append("BatchMode=yes")
        argv = ["ssh", "-T", "-N"]
        if self.identity:
            argv += ["-i", self.identity]
        for opt in opts:
            argv += ["-o", opt]
        argv += ["-R", "127.0.0.1:%d:127.0.0.1:%d" % (
            self.remote_port, self.local_port),
                 "-p", str(self.spec["port"]), "-l", self.spec["user"],
                 self.spec["host"]]
        return argv, env

    def start(self):
        if shutil.which("ssh") is None:
            self.error = "本机缺少 ssh 命令"
            return False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", self.local_port)) == 0:
                self.error = "本地 SOCKS 端口 %d 已被占用" % self.local_port
                return False
        argv, env = self._local_command()
        local = self._spawn(argv, env, "local", self.local_port)
        for _ in range(30):
            if local.poll() is not None:
                break
            if self._socks_ready(self.local_port):
                break
            time.sleep(0.2)
        if local.poll() is not None or not self._socks_ready(self.local_port):
            self.error = ("本地 SSH SOCKS5 未就绪（需本机开启 sshd，"
                          "可先用 ssh localhost 测试）")
            self.close()
            return False
        argv, env = self._remote_command()
        remote = self._spawn(argv, env, "remote", self.remote_port)
        for _ in range(25):
            if remote.poll() is not None:
                break
            time.sleep(0.2)
        if remote.poll() is not None:
            self.error = "远端 SOCKS 反向转发失败（端口被占用或认证失败）"
            self.close()
            return False
        self.ready = True
        remote_log("socks_share_ready", host=self.spec["display"],
                   remote_port=self.remote_port, local_port=self.local_port)
        return True

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.ready = False
        for proc in self._procs:
            stdin = getattr(proc, "stdin", None)
            if stdin is not None and not stdin.closed:
                try:
                    stdin.close()
                except OSError:
                    pass
        for proc in self._procs:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
        for log in self._logs:
            try:
                log.close()
            except OSError:
                pass
        self._logs = []
        if self._askpass_path:
            try:
                os.unlink(self._askpass_path)
            except FileNotFoundError:
                pass
            self._askpass_path = None
        remote_log("socks_share_closed", host=self.spec["display"],
                   remote_port=self.remote_port, local_port=self.local_port)


class RemoteForwardChannel:
    """把远端 mt.server 的 HTTP 服务经 ssh -L 暴露到本地 -p 端口。

    mode="tcp" ：远端只监听 127.0.0.1:<remote_port>，-P 指定端口，强制 token。
    mode="unix"：远端只监听 Unix socket，token 可选；默认由远端生成并在本地显示。
    远端命令用 exec 前台运行且不落日志，stdout/stderr 全部经 ssh 回传本地；
    ssh 退出时远端进程随之结束，不会留下孤儿服务。
    """

    def __init__(self, spec, server_cmd, mode, local_port, remote_port=None,
                 socket_path=None, directory="/", password=None, no_token=False,
                 home="/", verbose=True):
        self.spec = spec
        self.server_cmd = list(server_cmd)
        self.mode = mode
        self.local_port = int(local_port)
        self.remote_port = int(remote_port) if remote_port else None
        self.socket_path = (socket_path or os.environ.get("MCTA_REMOTE_SOCKET")
                            or DEFAULT_FORWARD_SOCKET)
        self.home = home or "/"
        self.directory = posixpath.normpath(directory or "/")
        self.password = password
        self.no_token = bool(no_token)
        self.verbose = verbose
        self.identity = identity_for(spec)
        self.token = ""
        self.error = ""
        self.ready = False
        self.proc = None
        self.lines = []
        self._lock = threading.Lock()
        self._closed = False
        self._reader = None
        self._askpass_path = None
        _RENDER_CHANNELS.add(self)

    @property
    def remote_socket(self):
        path = self.socket_path
        if path.startswith("~/"):
            return posixpath.normpath(posixpath.join(self.home, path[2:]))
        if path.startswith("~"):
            return posixpath.normpath(posixpath.join(self.home, path[1:].lstrip("/")))
        if path.startswith("/"):
            return posixpath.normpath(path)
        return posixpath.normpath(posixpath.join(self.home, path))

    @property
    def url(self):
        base = "http://127.0.0.1:%d/" % self.local_port
        return base if self.no_token or not self.token else base + "?t=" + self.token

    def _make_askpass(self):
        fd, path = tempfile.mkstemp(prefix="mcta-askpass-", suffix=".sh")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nprintf '%s' \"$MCTA_ASKPASS_SECRET\"\n")
        os.chmod(path, 0o700)
        self._askpass_path = path
        return path

    def _command(self):
        """构造 ssh -L 命令；密码只经 askpass 环境变量传递。"""
        server = " ".join(shlex.quote(str(x)) for x in self.server_cmd)
        if self.mode == "tcp":
            target = "127.0.0.1:%d" % self.remote_port
            run = ("%s -p %d -L 127.0.0.1 -f -Y -d %s"
                   % (server, self.remote_port, shlex.quote(self.directory)))
        else:
            sock = self.remote_socket
            directory = posixpath.dirname(sock)
            extra = " --no-token" if self.no_token else ""
            run = ("%s --socket %s -f -Y%s -d %s"
                   % (server, shlex.quote(sock), extra, shlex.quote(self.directory)))
            target = sock
        # 远端用薄壳包一层并 trap 退出信号：即使本地被强杀、sshd 只发 SIGHUP，
        # 也会显式结束 mt.server，不留孤儿进程。
        wrapped = ("%s & __mcta_pid=$!; "
                   "trap 'kill $__mcta_pid 2>/dev/null' HUP INT TERM EXIT; "
                   "while IFS= read -r __mcta_line; do :; done; "
                   "kill $__mcta_pid 2>/dev/null; wait $__mcta_pid 2>/dev/null") % run
        if self.mode == "unix":
            sock_dir = posixpath.dirname(self.remote_socket)
            inner = ("mkdir -p %s && (chmod 700 %s 2>/dev/null || true) && "
                     "sh -c %s"
                     % (shlex.quote(sock_dir), shlex.quote(sock_dir), shlex.quote(wrapped)))
        else:
            inner = "sh -c " + shlex.quote(wrapped)
        opts = [
            "KexAlgorithms=+diffie-hellman-group14-sha1",
            "HostKeyAlgorithms=+ssh-rsa",
            "ServerAliveInterval=30",
            "ExitOnForwardFailure=yes",
            "ConnectTimeout=8",
            "StrictHostKeyChecking=accept-new",
        ]
        if self.identity:
            opts.append("PubkeyAcceptedKeyTypes=+ssh-rsa")
        env = dict(os.environ)
        # 远端 token 必须由远端自己生成；不要继承本地可能存在的 token 环境。
        env.pop("MCTA_SERVER_TOKEN", None)
        env.pop("MCTA_SERVER_NO_TOKEN", None)
        if self.password:
            opts += [
                "BatchMode=no",
                "PreferredAuthentications=password,keyboard-interactive",
                "PubkeyAuthentication=no",
                "NumberOfPasswordPrompts=1",
            ]
            env.update(SSH_ASKPASS=self._make_askpass(),
                       SSH_ASKPASS_REQUIRE="force",
                       DISPLAY=os.environ.get("DISPLAY") or ":0",
                       MCTA_ASKPASS_SECRET=self.password)
        else:
            opts.append("BatchMode=yes")
        argv = ["ssh", "-T"]
        if self.identity:
            argv += ["-i", self.identity]
        for opt in opts:
            argv += ["-o", opt]
        argv += ["-L", "127.0.0.1:%d:%s" % (self.local_port, target),
                 "-p", str(self.spec["port"]), "-l", self.spec["user"],
                 self.spec["host"], inner]
        return argv, env

    @staticmethod
    def _port_open(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex(("127.0.0.1", port)) == 0

    def _pump(self):
        try:
            for raw in self.proc.stdout:
                line = raw.rstrip("\r\n")
                with self._lock:
                    self.lines.append(line)
                if self.verbose:
                    print("[remote] " + line, file=sys.stdout, flush=True)
                # TCP 模式从 URL 的 ?t= 取 token；Unix socket 模式从横幅的 token值 取。
                match = re.search(r"(?:[?&]t=|token值\s+)([A-Za-z0-9_-]+)", line)
                if match and not self.token:
                    self.token = match.group(1)
        except Exception as exc:  # noqa: BLE001 - 输出流异常只影响日志展示
            with self._lock:
                self.lines.append("读取远端输出失败：%s" % exc)

    def _probe(self):
        if not self._port_open(self.local_port):
            return False
        path = "/api/info" if self.no_token or not self.token else "/api/info?t=" + self.token
        conn = None
        try:
            conn = http.client.HTTPConnection("127.0.0.1", self.local_port, timeout=1)
            conn.request("GET", path, headers={"Connection": "close"})
            resp = conn.getresponse()
            resp.read(4096)
            return resp.status == 200
        except Exception:  # noqa: BLE001 - 未就绪时继续等待
            return False
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def start(self, timeout=25):
        started = time.monotonic()
        if shutil.which("ssh") is None:
            self.error = "本机缺少 ssh 命令"
            return False
        if self._port_open(self.local_port):
            self.error = ("本地端口 %d 已被占用，无法建立转发；请用 -p 换一个端口。"
                          % self.local_port)
            return False
        argv, env = self._command()
        try:
            self.proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, env=env, bufsize=1,
                text=True, start_new_session=True)
        except OSError as exc:
            self.error = "ssh 进程启动失败：%s" % str(exc)[:120]
            return False
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        while time.monotonic() - started < timeout:
            if self.proc.poll() is not None:
                with self._lock:
                    tail = self.lines[-5:]
                self.error = ("远端 mt.server 启动失败（ssh 已退出）：%s"
                              % (" / ".join(tail) if tail else "远端无输出"))
                self.close()
                return False
            if (self.no_token or self.token) and self._probe():
                self.ready = True
                remote_log("remote_forward", host=self.spec["display"], result="ready",
                           mode=self.mode, local_port=self.local_port,
                           token=bool(self.token),
                           elapsed_ms=int((time.monotonic() - started) * 1000))
                return True
            time.sleep(0.2)
        self.error = ("转发建立超时：本地端口 %d 未收到远端服务响应；"
                      "请查看上方远端输出。" % self.local_port)
        self.close()
        return False

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.ready = False
        proc = self.proc
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        if proc is not None and proc.stdin is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass
        if self._reader is not None and self._reader.is_alive():
            self._reader.join(timeout=1)
        if self._askpass_path:
            try:
                os.unlink(self._askpass_path)
            except FileNotFoundError:
                pass
            self._askpass_path = None
        remote_log("remote_forward_closed", host=self.spec["display"],
                   mode=self.mode, local_port=self.local_port)


class RemoteSSH:
    """终端专用的 SSH 连接，是四条独立通道中的终端通道。

    目录浏览由 :class:`RemoteFS` 的 browse 通道承担，文件传输由多条传输通道的
    SSH + SFTP 连接承担；本类只维护终端这一条 SSH 连接及其上的交互 shell，
    这样大文件传输既不会阻塞终端，也不会阻塞目录浏览或其它传输。
    """

    def __init__(self, spec, password=None, prompt=False, verbose=True,
                 client=None, auth=None, root="/"):
        self.spec = spec
        self._password = password
        self.root = posixpath.normpath(root or "/")
        if client is None:
            self.client, self.auth = connect(spec, password=password,
                                             prompt=prompt, verbose=verbose)
        else:
            self.client, self.auth = client, auth or "prechecked"
        self._closing = False
        self._lock = threading.RLock()
        self._reconnect_lock = threading.RLock()
        self._terminals = weakref.WeakSet()

    @classmethod
    def from_env(cls, root="/", verbose=False):
        spec = spec_from_env()
        if spec is None:
            return None
        return cls(spec, prompt=False, verbose=verbose, root=root)

    def write_rc(self, path, content):
        """用自己的 SSH 连接临时开一个 SFTP 通道写 rc 文件。"""
        sftp = self.client.open_sftp()
        try:
            with sftp.open(path, "w") as handle:
                handle.write(content)
        finally:
            try:
                sftp.close()
            except Exception:
                pass

    def is_conn_error(self, exc):
        return RemoteFS._is_conn_error(exc)

    def _reconnect(self):
        with self._reconnect_lock:
            if self._closing:
                raise RemoteError("远程服务正在关闭")
            print("[ssh] 终端连接已断开，正在重连 %s…" % self.spec["display"],
                  file=sys.stderr, flush=True)
            try:
                self.client.close()
            except Exception:
                pass
            try:
                client, auth = connect(self.spec, password=self._password,
                                       prompt=False, verbose=False)
                self.client, self.auth = client, auth
            except PasswordRequired as exc:
                raise RemoteError("终端 SSH 断连，自动重连需要密码但不可交互：%s" % exc)
            for term in list(self._terminals):
                try:
                    term.reconnect()
                except Exception:
                    pass

    def reconnect(self):
        self._reconnect()

    def close(self):
        self._closing = True
        try:
            self.client.close()
        except Exception:
            pass


_OSC_CWD = re.compile(rb"\x1b\]7;file://([^\x07]+)\x07")

# 静默设置 OSC 7 目录跟踪：通过 exec_command 让服务端启动带自定义 rc 的 bash，
# 设置命令由服务端直接执行，不会像交互输入那样被 tty 回显。
_PROMPT_SETUP = b"export PROMPT_COMMAND='printf \"\\033]7;file://%s\\007\" \"$PWD\"'"


class _RemoteTerminal:
    """与本地 _Terminal 接口一致的 SSH 交互 shell。"""

    def __init__(self, fs, rows, cols):
        self.fs = fs
        self.subs = []
        self.subs_lock = threading.Lock()
        self.backlog = bytearray()
        self.alive = True
        self.rows, self.cols = int(rows), int(cols)
        self.cwd_value = fs.root
        self.channel = None
        self._last_recover = 0.0
        self._hide_setup = False
        self._setup_buf = bytearray()
        fs._terminals.add(self)
        self._open_channel()
        threading.Thread(target=self._reader, daemon=True).start()

    def _write_shell_rc(self):
        """在远程写临时 bashrc：加载用户配置后静默设置 OSC 7 并进入初始目录。"""
        rc = "/tmp/mcta-shell-rc-%d" % os.getpid()
        content = (
            '[ -f /etc/profile ] && . /etc/profile\n'
            '[ -f "$HOME/.profile" ] && . "$HOME/.profile"\n'
            '[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"\n'
            + _PROMPT_SETUP.decode("utf-8") + "\n"
            + "cd " + shlex.quote(self.cwd_value) + "\n"
        )
        if hasattr(self.fs, "write_rc"):
            self.fs.write_rc(rc, content)
        else:
            with self.fs.sftp.open(rc, "w") as handle:
                handle.write(content)
        return rc

    def _open_channel(self):
        channel = None
        try:
            transport = self.fs.client.get_transport()
            channel = transport.open_session()
            channel.get_pty(
                term="xterm-256color",
                width=max(20, self.cols), height=max(4, self.rows))
            channel.set_combine_stderr(True)
            rc = self._write_shell_rc()
            # sshd 直接执行这条命令，输入回显机制不会介入，
            # 因此 PROMPT_COMMAND 与 cd 都不会出现在 xterm 里。
            channel.exec_command("exec bash --rcfile " + shlex.quote(rc) + " -i")
            self._hide_setup = False
        except Exception:
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass
            channel = self.fs.client.invoke_shell(
                term="xterm-256color", width=max(20, self.cols), height=max(4, self.rows))
            channel.set_combine_stderr(True)
            # 兜底：交互方式仍会回显，读取端负责隐藏这两行。
            self._hide_setup = True
            self._setup_buf.clear()
            channel.sendall(_PROMPT_SETUP + b"\n")
            channel.sendall(("cd " + shlex.quote(self.cwd_value) + "\n").encode("utf-8"))
        self.channel = channel

    def reconnect(self):
        """SSH 连接重建后恢复 shell，并尽量回到断线前的目录。"""
        if not self.alive:
            return
        try:
            if self.channel is not None:
                self.channel.close()
        except Exception:
            pass
        self._open_channel()
        self._publish(("\n[ssh] 连接已恢复，当前目录：%s\n" % self.cwd_value).encode("utf-8"))

    def _publish(self, data):
        with self.subs_lock:
            if data:
                self.backlog.extend(data)
                if len(self.backlog) > 262144:
                    del self.backlog[:-262144]
            subs = list(self.subs)
        for sub in subs:
            try:
                sub.put_nowait(data)
            except Exception:
                pass

    def subscribe(self):
        import queue
        sub = queue.Queue(maxsize=8192)
        with self.subs_lock:
            self.subs.append(sub)
            snapshot = bytes(self.backlog)
        if snapshot:
            try:
                sub.put_nowait(snapshot)
            except Exception:
                pass
        return sub

    def unsubscribe(self, sub):
        with self.subs_lock:
            try:
                self.subs.remove(sub)
            except ValueError:
                pass

    def _recover(self):
        """断线后重建连接和 shell；失败时限速重试，避免风暴。"""
        if not self.alive or getattr(self.fs, "_closing", False):
            return False
        now = time.time()
        if now - self._last_recover < 2:
            time.sleep(0.2)
            return False
        self._last_recover = now
        try:
            self.fs._reconnect()
            return True
        except Exception as exc:
            self._publish(("\n[ssh] 自动重连失败：%s\n" % exc).encode("utf-8"))
            time.sleep(1)
            return False

    def _filter_setup_echo(self, data):
        """兜底路径下隐藏 PROMPT_COMMAND 设置行的回显，其余输出原样返回。"""
        if not self._hide_setup:
            return data
        buf = self._setup_buf + bytearray(data)
        idx = buf.find(_PROMPT_SETUP)
        if idx >= 0:
            end = buf.find(b"\n", idx)
            if end < 0:
                self._setup_buf = buf
                return b""
            out = bytes(buf[:idx]) + bytes(buf[end + 1:])
            self._hide_setup = False
            self._setup_buf.clear()
            return out
        # 已收到 OSC 7 或缓冲过长时放弃过滤，避免吞掉正常输出。
        if _OSC_CWD.search(bytes(buf)) or len(buf) > 1024:
            self._hide_setup = False
            self._setup_buf.clear()
            return bytes(buf)
        self._setup_buf = buf
        return b""

    def _reader(self):
        while self.alive:
            try:
                channel = self.channel
                if channel is None or channel.closed:
                    self._recover()
                    continue
                if channel.recv_ready():
                    data = channel.recv(65536)
                    if not data:
                        if self._recover():
                            continue
                        break
                    for hit in _OSC_CWD.findall(data):
                        try:
                            self.cwd_value = posixpath.normpath(unquote(hit.decode("utf-8")))
                        except Exception:
                            pass
                    self._publish(self._filter_setup_echo(data))
                else:
                    time.sleep(0.05)
            except Exception:
                if not self.alive:
                    break
                if not self._recover():
                    continue
        self.alive = False
        self._publish(b"")

    def write(self, data):
        if not self.alive:
            return
        try:
            if self.channel is not None and not self.channel.closed:
                self.channel.sendall(data)
                return
        except Exception:
            pass
        if self._recover():
            try:
                self.channel.sendall(data)
            except Exception:
                pass

    def resize(self, rows, cols):
        try:
            self.channel.resize_pty(width=max(20, int(cols)), height=max(4, int(rows)))
        except Exception:
            pass

    def cwd(self):
        return self.cwd_value

    def close(self):
        self.alive = False
        try:
            self.channel.close()
        except Exception:
            pass
