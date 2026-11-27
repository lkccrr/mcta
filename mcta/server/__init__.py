"""mt.server —— 本地文件与终端服务（浏览器界面）。

    mt.server                  在后台启动服务，默认 http://127.0.0.1:9068/?t=TOKEN
    mt.server -p 8080          指定端口
    mt.server -c|--socket [PATH] Unix socket 提供 HTTP（不监听 TCP），
                                 默认 ~/.config/mcta/sock/mcta.sock，-S 可停止
    mt.server -f               在当前终端直接运行，Ctrl+C 停止
    mt.server -L 0.0.0.0       监听所有网卡（需输入 yes 确认，会打印安全警告）
    mt.server -N               不启用 token（需输入 yes 确认）
    mt.server -o [PATH]        输出日志文件（默认不写，同名文件覆盖）
    mt.server -R user@host:22  通过 SSH/SFTP 浏览远程服务器（用户/端口可省，默认本机用户名/22）
    mt.server -R host -P 9069  远端 mt.server 监听 TCP 9069，经 ssh -L 转回本地 -p（强制 token）
    mt.server -R host --socket 远端 mt.server 只开 Unix socket，经 ssh -L 转回本地 -p（token 可选）
    mt.server -S               停止后台服务

同一端口已有 mt.server 在运行时，会先停止旧服务再启动新的；启动它的终端
关闭或退出后，后台服务会自动停止。

服务以当前用户身份运行；文件浏览/编辑跟随运行目录与终端当前目录，终端仍是完整 shell，
提供与 SSH 一致的交互式终端（xterm.js + PTY）。每次启动都会生成新的
随机 token 并写进 URL，所有请求都要校验；默认只监听回环地址，不要将
带 token 的链接分享给他人，也不要对外网开放。

-R/--ssh 开启远程模式：启动前先按 OpenSSH 的 BatchMode/ConnectTimeout 方式非交互探测，
优先使用 ssh-agent 和 ~/.ssh 下的本地私钥；没有可用密钥或密钥认证失败时不再询问，
直接进入密码输入并自动转为前台运行（getpass 不回显，90 秒未输入超时或按 Ctrl+Z
自动结束进程；密码不写命令行/环境变量/日志）。-R 支持
user@host:22、user@host 22、user host 22、host 22、host 等写法，用户名默认本机用户，端口默认 22。
此时 -d 表示服务器上的目录，路径无效则使用 SSH 默认目录；目录列表、上传和下载来自
独立的 SSH/SFTP 连接，终端使用另一条 SSH 连接，大文件传输不会阻塞 shell。
文件正文下载到本机 ~/.cache/mcta 缓存目录后交给文本查看/ase/3Dmol，按服务器固定目录名、退出不删除、下次复用；拖入本地文件或目录即可上传到当前路径。
运行时自动补回 paramiko 5 移除的旧版算法
（group14-sha1 / group1-sha1 / ssh-rsa），无需降级 paramiko；SSH 端口写在 -R 中，-p 仍是网页端口。
连接断开会自动重建 SSH/SFTP 与终端 shell。

-R 模式下若远端装有兼容的 mt.server，3D 渲染会走第五条独立通道：本地系统 ssh
把回环端口转发到远端 ~/.config/mcta/sock/mcta-render.sock，远端解析/降采样后只回传精简数据；
远端不监听 TCP 端口，隧道断开后渲染自动回退到 SFTP + 本地解析。可用环境变量
MCTA_REMOTE_SOCKET 改 socket 路径（-c/--socket 默认也用这个路径），
MCTA_REMOTE_RENDER_MIN_MB 改阈值（默认 8 MB）。
终端、目录浏览、上传、下载仍走原来的四条通道，不受影响。

-R 还可直接把远端 mt.server 的网页服务转回本地 -p 端口（本地不再起文件服务）：
`-R ... -P PORT` 让远端只监听 127.0.0.1:PORT，必须带 token；`-R ... --socket [PATH]`
让远端只监听 Unix socket，token 可选。两者都会先检测远端 mt.server，远端不写日志，
stdout/stderr 全部回传本地显示；本地端口被占用或远端启动失败会报错退出，Ctrl+C 终止时
远端进程随 SSH 会话一起结束。token 由远端生成并在本地显示，可用于打开转发后的地址。

实现分布在四个子模块：_remote.py（SSH/SFTP/渲染隧道）、_terminal.py（PTY/token）、
_handlers.py（HTTP/页面/渲染代理）、_structure.py（结构/电荷密度）；本模块只保留启动入口与进程管理。
"""

import argparse
import atexit
import hashlib
import getpass
import json
import os
import secrets
import signal
import stat
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from mcta import version_string

from ._handlers import _Server, _UnixServer, _make_handler
from ._remote import (
    DEFAULT_FORWARD_SOCKET, DEFAULT_RENDER_SOCKET, DEFAULT_SOCKS_PORT,
    SOCKS_PORTS_ENV, SSH_SPEC_ENV, RemoteError,
    RemoteFS, RemoteForwardChannel, RemoteSSH, SocksShare, cache_size_warning,
    check as check_ssh, parse_ssh_spec, remote_log,
)
from ._structure import (
    DENSITY_NAMES, DENSITY_PREFIXES, JSON_EXTS, LAMMPS_DATA_EXTS,
    MAX_DENSITY_BYTES, MAX_DENSITY_POINTS, MAX_STRUCT_BYTES,
    MAX_STRUCT_FRAMES, MAX_TRAJ_ATOMS, STRUCT_EXTS, STRUCT_NAMES,
    STRUCT_PREFIXES, _density_options, _is_structure, _is_vasp_density,
    _lammps_data_style, _read_atoms, _read_frames, _read_vasp_density,
)
from ._terminal import (
    GUARD_ENV, NOHUP_ENV, NO_TOKEN_ENV, ROOT_ENV, SKIP_CONFIRM_ENV,
    TOKEN_ENV, TOKEN_COOKIE, _CONF, _TERMINALS, _TERMINALS_LOCK,
    _clean_sid, _terminal_for, _token_matches,
)

DEFAULT_PORT = 9068
FORWARD_ENV = "MCTA_SERVER_FORWARD_CONF"


DEFAULT_HOST = "127.0.0.1"

# -f -o 时 stdout/stderr 转到日志文件；启动横幅和交互提示仍写回这里保存的终端流。
_TERMINAL_STREAMS = None
_LOG_PATH = None


# ------------------------------------------------------------------ 通用 ---
def _state_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(str(Path.home()), ".cache")
    path = Path(base) / "mcta"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pid_path(port):
    return _state_dir() / ("server-%d.pid" % port)


def _socket_pid_path(socket_path):
    """每个 Unix socket 路径单独记录 PID，允许多个 socket 服务并存。"""
    path = Path(socket_path).expanduser()
    try:
        path = path.resolve()
    except OSError:
        pass
    key = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]
    return _state_dir() / ("sock-%s.pid" % key)


def _write_pid(path, pid, socket_path=None):
    """PID 记录；socket 服务在第二行保存路径，供 -S/--status 显示。"""
    text = str(pid)
    if socket_path:
        text += "\n" + str(Path(socket_path).expanduser())
    path.write_text(text, encoding="utf-8")


def _read_pid(path):
    """返回 (pid, socket_path)；兼容只有 PID 一行的旧记录。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        pid = int(lines[0].strip())
    except (OSError, ValueError, IndexError):
        return 0, None
    sock = lines[1].strip() if len(lines) > 1 and lines[1].strip() else None
    return pid, sock


def _socket_in_use(socket_path):
    """Unix socket 是否正在被监听；不存在或只是残留文件返回 False。"""
    if os.name == "nt":
        return False
    path = str(Path(socket_path).expanduser())
    try:
        if not stat.S_ISSOCK(os.stat(path).st_mode):
            return False
    except OSError:
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            sock.connect(path)
        return True
    except OSError:
        return False


def _log_path(port):
    return Path.cwd() / ("mcta-server-%d.log" % port)


def _resolve_log(value, port):
    """把 -o 的取值转成日志文件路径；None 表示不输出日志。

    -o 不带参数：当前目录 mcta-server-<端口>.log
    -o 给目录：该目录下 mcta-server-<端口>.log
    -o 给文件：就用该文件
    """
    if value is None:
        return None
    if value == "":
        return _log_path(port)
    path = Path(value).expanduser()
    if path.is_dir():
        path = path / ("mcta-server-%d.log" % port)
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _term_streams():
    """返回终端提示应写入的流（日志重定向前就是当前 stdout/stderr）。"""
    if _TERMINAL_STREAMS is not None:
        return _TERMINAL_STREAMS
    return sys.stdout, sys.stderr


def _redirect_output_to_log(value, port):
    """-f -o：错误和访问日志写日志；启动横幅、交互提示留在终端。"""
    global _TERMINAL_STREAMS, _LOG_PATH
    path = _resolve_log(value, port)
    try:
        stream = open(path, "w", encoding="utf-8")
    except OSError as exc:
        print("ERROR: 无法写入日志文件 %s：%s" % (path, exc), file=sys.stderr)
        return None
    _TERMINAL_STREAMS = (sys.stdout, sys.stderr)
    _LOG_PATH = path
    sys.stdout = stream
    sys.stderr = stream
    atexit.register(stream.close)
    return stream


def _shown_host(host):
    if host in ("0.0.0.0", "", "localhost"):
        return "127.0.0.1"
    if host == "::":
        return "::1"
    return host


def _authority(host, port):
    shown = _shown_host(host)
    return ("[%s]:%d" if ":" in shown else "%s:%d") % (shown, port)


def _url(host, port, token):
    if not token:
        return "http://%s/" % _authority(host, port)
    return "http://%s/?t=%s" % (_authority(host, port), token)


def _is_loopback(host):
    return host in ("127.0.0.1", "localhost", "::1")


def _probe(host, port, token, timeout=0.6):
    url = "http://%s/api/info" % _authority(host, port)
    if token:
        url += "?t=" + token
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _probe_socket(socket_path, token, timeout=0.6):
    """通过 Unix socket 探测 /api/info，返回与 _probe 一致的信息。"""
    if os.name == "nt":
        return None
    path = str(Path(socket_path).expanduser())
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(path)
            query = "/api/info" + ("?t=" + token if token else "")
            sock.sendall(("GET %s HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
                          % query).encode())
            chunks = []
            while True:
                part = sock.recv(65536)
                if not part:
                    break
                chunks.append(part)
    except OSError:
        return None
    head, sep, body = b"".join(chunks).partition(b"\r\n\r\n")
    if not sep or b" 200 " not in head.split(b"\r\n", 1)[0]:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def _terminal_guard_pid():
    """找出当前终端所属的进程：终端关闭或 shell 退出后它就不在了。

    从父进程往上找第一个挂在 tty 上的祖先（通常是交互式 shell）；
    找不到（例如被管道/非交互方式调用）时返回 None，此时不做自动停止。
    """
    if os.name == "nt":
        return None
    pid = os.getppid()
    for _ in range(16):
        if pid <= 1:
            return None
        try:
            stat = Path("/proc/%d/stat" % pid).read_text()
        except OSError:
            return None
        try:
            # comm 字段可能含空格，从最后一个 ')' 之后切分：
            # rest = [state, ppid, pgrp, session, tty_nr, ...]
            rest = stat.rsplit(")", 1)[1].split()
            tty_nr = int(rest[4])
            ppid = int(rest[1])
        except (IndexError, ValueError):
            return None
        if tty_nr != 0:
            return pid
        pid = ppid
    return None


def _start_terminal_watch(httpd):
    """后台服务：启动它的终端关闭/退出后，自动停止服务。"""
    raw = os.environ.get(GUARD_ENV, "").strip()
    if not raw.isdigit():
        return
    guard = int(raw)

    def watch():
        while True:
            time.sleep(1.0)
            if not _pid_alive(guard):
                print("终端已退出，mt.server 自动停止")
                try:
                    sys.stdout.flush()
                except (AttributeError, ValueError):
                    pass
                httpd.shutdown()
                return

    threading.Thread(target=watch, daemon=True).start()


def _close_remote_resources():
    """退出前关闭远程连接；SIGTERM 处理器不能只 os._exit。

    否则第五条渲染通道的 ssh 子进程及远端 mt.server 会残留，
    占用默认 socket，下一次启动就会走“远端渲染通道不可用”回退。
    """
    socks = _CONF.get("socks_share")
    if socks is not None:
        try:
            socks.close()
        except Exception:
            pass
    channel = _CONF.get("remote_render")
    if channel is not None:
        try:
            channel.close()
        except Exception:
            pass
    forward = _CONF.get("remote_forward")
    if forward is not None:
        try:
            forward.close()
        except Exception:
            pass
    for term in list(_TERMINALS.values()):
        try:
            term.close()
        except Exception:
            pass
    remote = _CONF.get("remote_fs")
    if remote is not None:
        try:
            remote.close()
        except Exception:
            pass
    remote_ssh = _CONF.get("remote_ssh")
    if remote_ssh is not None:
        try:
            remote_ssh.close()
        except Exception:
            pass


def _install_signal_cleanup(port):
    """收到 SIGHUP/SIGTERM（终端关闭、kill）时清掉 PID 文件再退出。

    如果父进程启动时传了 --no-hup（通过 NOHUP_ENV 标记），子进程忽略 SIGHUP，
    只保留 SIGTERM（供 mt.server -S 终止）。
    """
    if os.name == "nt":
        return

    no_hup = os.environ.get(NOHUP_ENV, "") == "1"

    def handler(_signum, _frame):
        try:
            path = _pid_path(port)
            if path.exists() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                path.unlink(missing_ok=True)
        except OSError:
            pass
        _close_remote_resources()
        os._exit(0)

    sigs = (signal.SIGTERM,) if no_hup else (signal.SIGHUP, signal.SIGTERM)
    for sig in sigs:
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


def _install_socket_cleanup(httpd, pid_file):
    """Unix socket 模式：进程退出（含 SIGTERM/SIGHUP）时清理 socket 与 PID 文件。"""
    if os.name == "nt":
        return

    no_hup = os.environ.get(NOHUP_ENV, "") == "1"

    def handler(_signum, _frame):
        try:
            httpd.unlink_socket()
        except OSError:
            pass
        try:
            pid, _sock = _read_pid(pid_file)
            if pid == os.getpid():
                pid_file.unlink(missing_ok=True)
        except OSError:
            pass
        _close_remote_resources()
        os._exit(0)

    sigs = (signal.SIGTERM,) if no_hup else (signal.SIGHUP, signal.SIGTERM)
    for sig in sigs:
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


def _start_forward_background(conf, port, log=None, no_hup=False):
    """密钥认证下把远端转发通道放到后台子进程持有。"""
    cmd = [sys.executable, "-m", "mcta", "server", "--serve-forward",
           "-p", str(port)]
    env = dict(os.environ, **{FORWARD_ENV: json.dumps(conf, ensure_ascii=False),
                              SKIP_CONFIRM_ENV: "1"})
    if no_hup:
        env[NOHUP_ENV] = "1"
        env.pop(GUARD_ENV, None)
    else:
        guard = _terminal_guard_pid()
        if guard:
            env[GUARD_ENV] = str(guard)
        else:
            env.pop(GUARD_ENV, None)
    log_fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600) if log else None
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": os.fdopen(log_fd, "wb", closefd=True) if log_fd is not None else subprocess.DEVNULL,
        "stderr": subprocess.STDOUT,
        "cwd": tempfile.gettempdir(),
        "env": env,
    }
    if os.name != "nt":
        kwargs["preexec_fn"] = lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN)
    proc = subprocess.Popen(cmd, **kwargs)
    if kwargs["stdout"] is not subprocess.DEVNULL:
        kwargs["stdout"].close()
    pid_file = _pid_path(port)
    _write_pid(pid_file, proc.pid, None)
    state = _forward_state_path(port)
    info = None
    for _ in range(150):
        if proc.poll() is not None:
            break
        if state.exists():
            try:
                info = json.loads(state.read_text(encoding="utf-8"))
                break
            except (OSError, ValueError):
                pass
        time.sleep(0.2)
    if info is None:
        try:
            proc.terminate()
        except OSError:
            pass
        pid_file.unlink(missing_ok=True)
        print("ERROR: 后台转发通道未能就绪，请用 -f 前台运行查看原因。", file=sys.stderr)
        return 2
    print("McTa 远程转发服务已在后台启动")
    print("  地址    " + info["url"])
    print("  远端    " + info["display"])
    print("  模式    %s" % ("TCP 端口转发（强制 token）" if conf["mode"] == "tcp"
                            else "Unix socket 转发（token %s）"
                            % ("关闭" if conf.get("no_token") else "远端生成")))
    if conf["mode"] == "tcp":
        print("  远端端口 %d" % conf["remote_port"])
    else:
        print("  远端 socket " + info["remote_socket"])
    print("  本地端口 %d" % port)
    if conf.get("socks_ports"):
        sp = conf["socks_ports"]
        print("  SOCKS5  远端 %d → 本地 %d（出口本地网络）" % (sp[0], sp[1]))
    print("  进程    %d" % proc.pid)
    print("  停止    " + ("mt.server -S" if no_hup else "mt.server --stop") + (
        "（--no-hup：关闭启动终端不影响服务，只能手动终止）" if no_hup else ""))
    print("  日志    " + (str(log) if log else "未输出（加 -o 可开启）"))
    return 0
def _serve(host, port, token, socket_path=None):
    _CONF["token"] = token
    _CONF["no_token"] = not token
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:  # pragma: no cover - 老版本 Python
        pass
    remote = _CONF.get("remote_fs")
    if remote is None:
        try:
            remote = RemoteFS.from_env()
        except RemoteError as exc:
            print("ERROR: 远程 SFTP 连接失败：%s" % exc, file=sys.stderr)
            return 2
        if remote is not None:
            _CONF["remote_fs"] = remote
    remote_ssh = _CONF.get("remote_ssh")
    if remote is not None and remote_ssh is None:
        try:
            remote_ssh = RemoteSSH.from_env(root=remote.root)
        except RemoteError as exc:
            print("ERROR: 终端 SSH 连接失败：%s" % exc, file=sys.stderr)
            if remote is not None:
                remote.close()
            return 2
        if remote_ssh is not None:
            _CONF["remote_ssh"] = remote_ssh
    if remote is not None:
        _CONF["user"] = remote.spec["user"]
        _CONF["start"] = str(remote.root_local)
        remote_log("connect", host=remote.display, root=remote.root, auth=remote.auth)
        # 第五条通道只服务 3D 渲染；失败不抛异常，渲染请求自动回退本地。
        wanted = os.environ.get("MCTA_REMOTE_SOCKET") or DEFAULT_RENDER_SOCKET
        channel = remote.start_render_channel(wanted)
        _CONF["remote_render"] = channel
        if channel is None:
            reason = getattr(remote, "_render_error", "") or ""
            msg = ("[remote] 3D 渲染远端通道未就绪（%s），使用本地解析" % reason
                   if reason else "[remote] 3D 渲染远端通道未就绪，使用本地解析")
            print(msg, file=sys.stderr, flush=True)
    if remote is not None:
        socks = _CONF.get("socks_share")
        if socks is None:
            pair = _CONF.get("socks_ports") or os.environ.get(SOCKS_PORTS_ENV, "")
            if pair:
                try:
                    if isinstance(pair, (tuple, list)):
                        rport, lport = pair
                    else:
                        rport, lport = [int(x) for x in str(pair).split(":")]
                except (TypeError, ValueError):
                    rport = lport = 0
                if 0 < rport < 65536 and 0 < lport < 65536:
                    socks = SocksShare(remote.spec, rport, lport,
                                       password=_CONF.get("ssh_password"),
                                       client=remote.client, verbose=False)
                    if not socks.start():
                        print("ERROR: SOCKS5 共享失败：%s" % socks.error,
                              file=sys.stderr)
                        _close_remote_resources()
                        return 2
                    _CONF["socks_share"] = socks
    handler = _make_handler()
    pid_file = _socket_pid_path(socket_path) if socket_path else _pid_path(port)
    httpd = _UnixServer(socket_path, handler) if socket_path else _Server(host, port, handler)
    if socket_path:
        _install_socket_cleanup(httpd, pid_file)
    else:
        _install_signal_cleanup(port)
    _start_terminal_watch(httpd)
    out, _err = _term_streams()
    print("McTa 文件服务", file=out, flush=True)
    if socket_path:
        print("  Unix    " + str(Path(socket_path).expanduser()), file=out, flush=True)
        print("  网络    不监听 TCP 端口（SSH 22 除外）", file=out, flush=True)
    else:
        print("  地址    " + _url(host, port, token), file=out, flush=True)
    if remote is not None:
        print("  远程    " + remote.display + "（" + remote.auth + "）", file=out, flush=True)
        print("  远程目录 " + remote.root, file=out, flush=True)
        print("  本地缓存 " + str(remote.cache_root), file=out, flush=True)
    else:
        print("  运行目录 " + str(Path(_CONF["start"]).resolve()), file=out, flush=True)
    if _CONF.get("socks_share"):
        share = _CONF["socks_share"]
        print("  SOCKS5  远端 %d → 本地 %d（出口本地网络）"
              % (share.remote_port, share.local_port), file=out, flush=True)
    print("  账户    " + _CONF["user"], file=out, flush=True)
    print("  token   " + ("未启用（-N：直接凭地址和端口访问）" if not token
                          else "每次启动随机生成，重启后旧链接失效"), file=out, flush=True)
    if token and socket_path:
        # Unix socket 模式没有带 token 的 URL；直接打印 token 供本地转发等工具读取。
        print("  token值  " + token, file=out, flush=True)
    print("  停止    Ctrl+C", file=out, flush=True)
    if _LOG_PATH is not None:
        print("  日志    " + str(_LOG_PATH), file=out, flush=True)
    print("", file=out, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
        _close_remote_resources()
        # 后台服务自行退出时，清掉自己的 PID 记录
        try:
            pid, _sock = _read_pid(pid_file)
            if pid == os.getpid():
                pid_file.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


def _forward_state_path(port):
    return _state_dir() / ("forward-%d.json" % port)


def _serve_forward(port):
    """后台子进程：重建远端转发通道并阻塞持有（父进程退出后仍存活）。"""
    raw = os.environ.get(FORWARD_ENV, "")
    try:
        conf = json.loads(raw)
    except (TypeError, ValueError):
        print("ERROR: 转发配置无效，无法启动后台转发。", file=sys.stderr)
        return 2
    try:
        spec = parse_ssh_spec([conf["ssh"]])
        if conf.get("identity"):
            spec["identity"] = conf["identity"]
    except (KeyError, RemoteError) as exc:
        print("ERROR: 转发 SSH 配置无效：%s" % exc, file=sys.stderr)
        return 2
    channel = RemoteForwardChannel(
        spec, conf["server_cmd"], conf["mode"], port,
        remote_port=conf.get("remote_port"),
        socket_path=conf.get("socket_path"),
        directory=conf.get("directory", "/"), password=None,
        no_token=bool(conf.get("no_token")), home=conf.get("home", "/"),
        verbose=False)
    if not channel.start():
        print("ERROR: %s" % channel.error, file=sys.stderr)
        return 2
    share = None
    socks = conf.get("socks_ports") or []
    if len(socks) == 2:
        share = SocksShare(spec, socks[0], socks[1], client=None, verbose=False)
        if not share.start():
            print("ERROR: SOCKS5 共享失败：%s" % share.error, file=sys.stderr)
            channel.close()
            return 2
        _CONF["socks_share"] = share
    _CONF["remote_forward"] = channel
    _install_signal_cleanup(port)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass
    state = {
        "url": channel.url,
        "display": spec["display"],
        "mode": conf["mode"],
        "remote_port": conf.get("remote_port"),
        "remote_socket": channel.remote_socket,
        "socks_ports": socks,
        "token": channel.token,
    }
    try:
        _forward_state_path(port).write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    out, _err = _term_streams()
    print("McTa 远程转发服务", file=out, flush=True)
    print("  地址    " + channel.url, file=out, flush=True)
    print("  远端    %s" % spec["display"], file=out, flush=True)
    print("  模式    %s" % ("TCP 端口转发（强制 token）" if conf["mode"] == "tcp"
                            else "Unix socket 转发（token %s）"
                            % ("关闭" if conf.get("no_token") else "远端生成")),
          file=out, flush=True)
    if conf["mode"] == "tcp":
        print("  远端端口 %d" % conf["remote_port"], file=out, flush=True)
    else:
        print("  远端 socket " + channel.remote_socket, file=out, flush=True)
    print("  本地端口 %d" % port, file=out, flush=True)
    if socks:
        print("  SOCKS5  远端 %d → 本地 %d（出口本地网络）" % (socks[0], socks[1]),
              file=out, flush=True)
    print("  停止    mt.server -S；远端进程随 SSH 会话一起结束", file=out, flush=True)
    print("", file=out, flush=True)
    try:
        while channel.ready and channel.proc is not None and channel.proc.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        channel.close()
        if share is not None:
            share.close()
        _forward_state_path(port).unlink(missing_ok=True)
    return 0
def _start_background(host, port, token, log=None, no_hup=False,
                      socket_path=None, socks_ports=None):
    if not socket_path and _port_open(host, port):
        print("ERROR: 端口 %d 已被其他程序占用，可用 -p 换一个端口。" % port, file=sys.stderr)
        return 2

    if socket_path:
        cmd = [sys.executable, "-m", "mcta", "server", "--serve",
               "--socket", socket_path]
    else:
        cmd = [sys.executable, "-m", "mcta", "server", "--serve",
               "--host", host, "-p", str(port)]
    env = dict(os.environ, **{TOKEN_ENV: token,
                              ROOT_ENV: str(Path.cwd().resolve()),
                              SKIP_CONFIRM_ENV: "1"})
    remote = _CONF.get("remote_fs")
    if remote is not None:
        env.update(remote.env())
    if not token:
        env[NO_TOKEN_ENV] = "1"
    if socks_ports:
        env[SOCKS_PORTS_ENV] = "%d:%d" % socks_ports
    if no_hup:
        env[NOHUP_ENV] = "1"
        env.pop(GUARD_ENV, None)
    else:
        # 记录启动它的终端进程：终端关闭/退出后由子进程自行停止
        guard = _terminal_guard_pid()
        if guard:
            env[GUARD_ENV] = str(guard)
        else:
            env.pop(GUARD_ENV, None)

    log_fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600) if log else None
    kwargs = {
        "stdin": subprocess.DEVNULL,
        # 默认不输出日志；给了 -o 才写日志文件，同名文件直接覆盖。
        # 启动横幅包含带 token 的 URL，日志文件必须仅属主可读。
        "stdout": os.fdopen(log_fd, "wb", closefd=True) if log_fd is not None else subprocess.DEVNULL,
        "stderr": subprocess.STDOUT,
        "cwd": tempfile.gettempdir(),
        "env": env,
    }
    # Unix：让子进程忽略 SIGHUP（关闭终端时不会自动收到挂断信号）。
    # no-hup 模式下我们还要显式设置，双保险。
    if os.name != "nt":
        kwargs["preexec_fn"] = lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN)

    proc = subprocess.Popen(cmd, **kwargs)
    # 父进程不再持有日志 fd；只保留子进程那一份。
    if kwargs["stdout"] is not subprocess.DEVNULL:
        kwargs["stdout"].close()

    pid_file = _socket_pid_path(socket_path) if socket_path else _pid_path(port)
    _write_pid(pid_file, proc.pid, socket_path)

    for _ in range(50):
        time.sleep(0.2)
        info = (_probe_socket(socket_path, token, timeout=0.5) if socket_path
                else _probe(host, port, token, timeout=0.5))
        if info:
            print("McTa 文件服务已在后台启动")
            if socket_path:
                print("  Unix    " + str(Path(socket_path).expanduser()))
            else:
                print("  地址    " + _url(host, port, token))
            if info.get("remote"):
                print("  远程    " + str(info.get("remoteHost") or ""))
                print("  远程目录 " + str(info.get("remoteRoot") or ""))
                print("  本地缓存 " + str(info.get("cacheRoot") or ""))
            else:
                print("  运行目录 " + info["root"])
            if socks_ports:
                print("  SOCKS5  远端 %d → 本地 %d（出口本地网络）" % socks_ports)
            print("  账户    " + str(info["user"]))
            if socket_path and token:
                print("  token   " + token)
            else:
                print("  token   " + ("未启用（-N：直接访问）" if not token
                                      else "每次启动随机生成，重启后旧链接失效"))
            print("  进程    %d" % proc.pid)
            stop_hint = "mt.server -S" if no_hup else "mt.server --stop"
            print("  停止    " + stop_hint + (
                "（--no-hup：关闭启动终端不影响服务，只能手动终止）" if no_hup else ""))
            print("  日志    " + (str(log) if log else "未输出（加 -o 可开启）"))
            return 0

    if log:
        print("ERROR: 服务未能启动，请查看日志：" + str(log), file=sys.stderr)
    else:
        print("ERROR: 服务未能启动（未输出日志，可用 -o 查看详细输出）。", file=sys.stderr)
    return 2


def _port_open(host, port):
    target = _shown_host(host)
    try:
        family, _, _, _, sockaddr = socket.getaddrinfo(target, port, type=socket.SOCK_STREAM)[0]
    except OSError:
        return False
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(sockaddr) == 0


def _pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return str(pid).encode() in out.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _pid_is_server(pid):
    """尽量确认该 PID 仍是 mt.server，避免误杀被复用的 PID。"""
    try:
        raw = Path("/proc/%d/cmdline" % pid).read_bytes()
    except OSError:
        return True         # 无法确认时按原样处理
    if b"mcta.server" in raw or b"mt.server" in raw:
        return True
    args = raw.split(b"\0")
    try:
        idx = args.index(b"-m")
    except ValueError:
        return False
    return len(args) > idx + 2 and args[idx + 1] == b"mcta" and args[idx + 2] == b"server"


def _terminate_pid(pid):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def _stop_existing(port):
    """启动前停掉同一端口上已在运行的 mt.server。"""
    path = _pid_path(port)
    if not path.exists():
        return False
    try:
        pid, _sock = _read_pid(path)
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        return False
    if pid == os.getpid():      # 后台启动的子进程不要停掉自己
        return False
    if not _pid_alive(pid) or not _pid_is_server(pid):
        print("清理过期的 PID 记录（端口 %d，进程 %d 已不存在）。" % (port, pid))
        path.unlink(missing_ok=True)
        return False

    print("检测到端口 %d 上已有 mt.server（进程 %d），先停止它..." % (port, pid))
    if _terminate_pid(pid):
        for _ in range(40):
            time.sleep(0.1)
            if not _port_open("127.0.0.1", port):
                break
    path.unlink(missing_ok=True)
    return True


def _pid_is_socket_server(pid):
    """判断后台服务是否以 -c/--socket 启动（Unix socket 模式）。"""
    if os.name == "nt":
        return False
    try:
        raw = Path("/proc/%d/cmdline" % pid).read_bytes()
    except OSError:
        return False
    args = [a for a in raw.split(b"\0") if a]
    return b"--socket" in args or b"-c" in args


def _stop_pidfile(path, port):
    """终止一条 PID 记录对应的后台服务；返回 (找到记录, 返回码)。"""
    if not path.exists():
        return False, 0
    pid, _sock = _read_pid(path)
    if not pid:
        path.unlink(missing_ok=True)
        print("PID 文件损坏，已删除。")
        return True, 2
    if not _pid_alive(pid) or not _pid_is_server(pid):
        path.unlink(missing_ok=True)
        if port is None:
            print("Unix socket 上的服务已不在运行（进程 %d），已清理记录。" % pid)
        else:
            print("端口 %d 上的服务已不在运行（进程 %d），已清理记录。" % (port, pid))
        return True, 0
    if not _terminate_pid(pid):
        print("停止失败：进程 %d 无法终止。" % pid, file=sys.stderr)
        return True, 1
    path.unlink(missing_ok=True)
    if port is None:
        print("已停止 Unix socket 上的服务（进程 %d）。" % pid)
    else:
        print("已停止端口 %d 上的服务（进程 %d）。" % (port, pid))
    return True, 0


def _socket_pidfiles():
    return sorted(_state_dir().glob("sock-*.pid"))


def _stop(port, all_ports=True):
    """-S：停止当前用户的 mt.server（占用端口的服务 + 所有 -c socket 服务）。"""
    found, code = False, 0
    if all_ports:
        for path in sorted(_state_dir().glob("server-*.pid")):
            try:
                p = int(path.stem.split("-", 1)[1])
            except (IndexError, ValueError):
                continue
            f, c = _stop_pidfile(path, p)
            found = found or f
            code = max(code, c)
    else:
        f, c = _stop_pidfile(_pid_path(port), port)
        found = found or f
        code = max(code, c)
    for path in _socket_pidfiles():
        f, c = _stop_pidfile(path, None)
        found = found or f
        code = max(code, c)
    if not found:
        print("没有找到 mt.server 的后台服务记录。")
        return 2
    return code


def _server_records():
    """遍历本用户 PID 记录，返回 [(标识, 进程号, 是否存活, 是否 socket)]。"""
    records = []
    for path in _state_dir().glob("server-*.pid"):
        try:
            port = int(path.stem.split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        pid, _sock = _read_pid(path)
        records.append((port, pid, bool(pid) and _pid_alive(pid) and _pid_is_server(pid), False))
    for path in _socket_pidfiles():
        pid, sock = _read_pid(path)
        records.append((sock or path.stem, pid,
                        bool(pid) and _pid_alive(pid) and _pid_is_server(pid), True))
    records.sort(key=lambda r: (r[3], str(r[0])))
    return records


def _status():
    """列出本用户所有 mt.server 后台服务（端口与 Unix socket）。"""
    records = _server_records()
    if not records:
        print("当前用户没有 mt.server 的后台服务记录。")
        return 0
    print("%-32s %-8s %s" % ("服务", "进程", "状态"))
    running = 0
    for target, pid, alive, is_socket in records:
        if alive:
            running += 1
            state = "运行中"
        else:
            state = "已退出（记录过期）"
        shown = ("socket " + str(target)) if is_socket else ("端口 %d" % target)
        print("%-32s %-8s %s" % (shown, pid if pid else "-", state))
    print("共 %d 个服务记录，其中 %d 个运行中。" % (len(records), running))
    return 0


def _stop_all():
    """停止本用户所有 mt.server 后台服务（端口与 Unix socket）。"""
    code = 0
    found = False
    for path in sorted(_state_dir().glob("server-*.pid")):
        try:
            port = int(path.stem.split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        f, c = _stop_pidfile(path, port)
        found = found or f
        code = max(code, c)
    for path in _socket_pidfiles():
        f, c = _stop_pidfile(path, None)
        found = found or f
        code = max(code, c)
    if not found:
        print("当前用户没有 mt.server 的后台服务记录。")
    return code

def _confirm_risk(message):
    """危险启动选项的确认：必须在终端输入 yes 或 YES。"""
    out, _err = _term_streams()
    print("WARNING: " + message, file=out, flush=True)
    try:
        print("确认继续请输入 yes 或 YES：", file=out, end="", flush=True)
        ans = input().strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消启动。", file=out, flush=True)
        return False
    if ans.lower() == "yes":
        return True
    print("输入不是 yes/YES，已取消启动。", file=out, flush=True)
    return False


class _PasswordTimeout(Exception):
    """SSH 密码输入超时。"""


class _PasswordAbort(Exception):
    """SSH 密码输入时按下 Ctrl+Z。"""


def _read_ssh_password(prompt, timeout=90):
    """读取 SSH 密码：90 秒未输入超时，Ctrl+Z 结束进程。

    getpass 不回显；信号处理器只在密码提示期间生效，读完即恢复，
    不影响服务启动后的正常作业控制。Windows 无 SIGALRM/SIGTSTP，
    退化为普通 getpass。
    """
    if not hasattr(signal, "SIGALRM") or not hasattr(signal, "SIGTSTP"):
        return getpass.getpass(prompt, stream=_term_streams()[1])

    def on_alarm(_signum, _frame):
        raise _PasswordTimeout()

    def on_tstp(_signum, _frame):
        raise _PasswordAbort()

    old_alarm = signal.signal(signal.SIGALRM, on_alarm)
    old_tstp = signal.signal(signal.SIGTSTP, on_tstp)
    try:
        signal.alarm(int(timeout))
        return getpass.getpass(prompt, stream=_term_streams()[1])
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_alarm)
        signal.signal(signal.SIGTSTP, old_tstp)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="mt.server",
        description="本地文件服务：浏览目录、编辑文本、查看图片，并提供 SSH 级终端。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-v", "-V", "--version", action="store_true",
                        help="显示版本并退出")
    parser.add_argument("-h", "-H", "--help", action="help",
                        help="显示帮助并退出")
    parser.add_argument("-p", "--port", type=int, default=None,
                          help="监听端口，默认 %d；远程转发模式下为本地转发监听端口" % DEFAULT_PORT)
    socket_default = os.environ.get("MCTA_REMOTE_SOCKET") or DEFAULT_FORWARD_SOCKET
    parser.add_argument("-c", "--socket", nargs="?", const=socket_default, default=None,
                          metavar="PATH",
                          help="本地与 -p 互斥，后跟路径；配合 -R 为远端 Unix socket 路径，并转发本地端口")
    parser.add_argument("-f", "--serve", action="store_true",
                        help="前台运行（在当前终端直接提供服务，不转入后台）")
    parser.add_argument("-o", "--log", nargs="?", const="", default=None, metavar="PATH",
                        help="日志文件（默认不输出）；与 -f 同用时终端显示交互提示，启动/错误写日志")
    parser.add_argument("-d", "--run-dir", default=None, metavar="PATH",
                        help="本地模式为运行目录（默认当前目录）；远程模式为服务器目录")
    parser.add_argument("-R", "--ssh", nargs="+", default=None,
                        metavar=("u@h", ""),
                        help=("远程模式；配合 -P 或 -c 时把远端网页服务转回本地端口"))
    parser.add_argument("-i", "--ident", default=None, metavar="KEY",
                        help="配合 -R：指定 SSH 私钥文件；默认使用 ssh-agent 与 ~/.ssh 下的密钥")
    parser.add_argument("-P", "--rmt-port", type=int, default=None, metavar="PORT",
                        help="配合 -R：远端端口，转回本地 -p；远端只监听回环地址，强制启用 token")
    parser.add_argument("-D", "--dept", nargs="*", default=None,
                        metavar=("", ""),
                        help="配合 -R：共享本机网络给远端；可跟 （远端、本地），默认 %d" % DEFAULT_SOCKS_PORT)
    parser.add_argument("-N", "--no-token", action="store_true",
                        help="不启用 token 鉴权（需输入 yes 确认），直接用地址和端口访问")
    parser.add_argument("-L", "--host", default=DEFAULT_HOST, metavar="HOST",
                        help="监听地址，默认 127.0.0.1；对外监听（如 0.0.0.0）需输入 yes 确认")
    parser.add_argument("-Y", "--yes", action="store_true",
                        help="跳过危险启动选项的输入确认（配合 -L 非回环地址或 -N 使用）")
    parser.add_argument("--status", action="store_true",
                        help="列出本用户所有端口与 Unix socket 上运行的 mt.server")
    parser.add_argument("-S", "--stop", action="store_true",
                        help="停止后台服务（含 -c 的 Unix socket 服务）")
    parser.add_argument("--all", action="store_true",
                        help="配合 -S 使用：停止本用户所有端口与 Unix socket 上运行的 mt.server")
    parser.add_argument("--no-hup", action="store_true",
                        help="忽略 SIGHUP，不跟随启动终端退出；只能用 -S 或 -S --all 终止")
    parser.add_argument("--serve-forward", action="store_true",
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.serve_forward:
        return _serve_forward(args.port or DEFAULT_PORT)

    if args.version:
        print(version_string())
        return 0
    if args.status:
        return _status()
    if args.all and not args.stop:
        print("ERROR: --all 只能与 -S/--stop 一起使用。", file=sys.stderr)
        return 2
    port_explicit = args.port is not None
    if args.port is None:
        args.port = DEFAULT_PORT
    if not 0 < args.port < 65536:
        print("ERROR: 端口需在 1–65535 之间。", file=sys.stderr)
        return 2
    forward_mode = ""
    if args.rmt_port is not None:
        if not args.ssh:
            print("ERROR: -P 必须配合 -R 使用。", file=sys.stderr)
            return 2
        if args.socket:
            print("ERROR: -P 与 --socket 不能同时使用（均需 -R）。", file=sys.stderr)
            return 2
        if not 0 < args.rmt_port < 65536:
            print("ERROR: -P 的远端端口需在 1–65535 之间。", file=sys.stderr)
            return 2
        forward_mode = "tcp"
    elif args.ssh and args.socket:
        forward_mode = "unix"
    if args.socket and not forward_mode:
        args.socket = str(Path(args.socket).expanduser().resolve())
    socks_ports = None
    if args.dept is not None:
        if not args.ssh:
            print("ERROR: -D 必须配合 -R 使用。", file=sys.stderr)
            return 2
        if len(args.dept) > 2:
            print("ERROR: -D 最多跟两个端口（远端、本地）。", file=sys.stderr)
            return 2
        values = []
        for item in args.dept:
            value = int(item) if str(item).isdigit() else 0
            if not 0 < value < 65536:
                print("ERROR: -D 端口需在 1–65535 之间：%s" % item, file=sys.stderr)
                return 2
            values.append(value)
        if not values:
            rport = lport = DEFAULT_SOCKS_PORT
        elif len(values) == 1:
            rport = lport = values[0]
        else:
            rport, lport = values
        if forward_mode == "tcp" and rport == args.rmt_port:
            print("ERROR: -D 的远端端口 %d 与 -P 冲突。" % rport, file=sys.stderr)
            return 2
        if lport == args.port:
            print("ERROR: -D 的本地端口 %d 与网页端口 -p 冲突。" % lport,
                  file=sys.stderr)
            return 2
        socks_ports = (rport, lport)
    if args.ident and not args.ssh and not os.environ.get(SSH_SPEC_ENV):
        print("ERROR: -i 必须配合 -R 使用。", file=sys.stderr)
        return 2
    identity = ""
    if args.ident:
        key_path = Path(args.ident).expanduser()
        if not key_path.is_file():
            print("ERROR: SSH 私钥不存在：%s" % key_path, file=sys.stderr)
            return 2
        identity = str(key_path.resolve())
        try:
            if os.name != "nt" and key_path.stat().st_mode & 0o077:
                print("WARNING: 私钥 %s 权限过宽，建议 chmod 600。" % key_path,
                      file=sys.stderr)
        except OSError:
            pass
    no_token = args.no_token or os.environ.get(NO_TOKEN_ENV) == "1"
    if forward_mode == "tcp" and no_token:
        print("ERROR: -R -P 模式必须启用 token（远端 TCP 端口可能被他人访问）；请去掉 -N。",
              file=sys.stderr)
        return 2
    if not args.ssh and args.socket and port_explicit:
        print("ERROR: 本地模式下 --socket 与 -p 互斥。", file=sys.stderr)
        return 2
    if args.stop:
        return (_stop_all() if args.all
                else _stop(args.port, all_ports=not port_explicit))

    # -f -o：错误写日志；启动横幅和需要交互的提示仍显示在终端。
    if args.serve and args.log is not None:
        if _redirect_output_to_log(args.log, args.port) is None:
            return 2

    # 远程模式：先非交互探测，再连接 SSH/SFTP；-d 是服务器路径，无效则回退 SSH 默认目录。
    remote_fs = None
    ssh_password = None
    if args.ssh and not os.environ.get(SSH_SPEC_ENV):
        try:
            spec = parse_ssh_spec(args.ssh)
            if identity:
                spec["identity"] = identity
        except RemoteError as exc:
            print("ERROR: %s" % exc, file=sys.stderr)
            return 2
        if args.port != DEFAULT_PORT:
            print("WARNING: -p 设置的是 mt.server 网页端口；SSH 端口请写在 -R 中，"
                  "例如 -R user@host:2222。", file=sys.stderr)
        try:
            status = check_ssh(spec, verbose=True)
        except RemoteError as exc:
            print("ERROR: SSH 服务器不可用：%s" % exc, file=sys.stderr)
            return 2

        if status["password_required"]:
            if not sys.stdin.isatty():
                print("ERROR: %s 需要密码认证；请在交互终端运行，"
                      "密码不会写入命令行或日志。" % spec["display"], file=sys.stderr)
                return 2
            # 无可用密钥或密钥认证失败时直接进入密码输入，不再询问 y/N；
            # -Y/--yes 只用于其它危险选项确认，不跳过密码输入。
            print("密码认证需在当前终端输入，自动改用前台运行（-f）。",
                  file=_term_streams()[0], flush=True)
            args.serve = True
            try:
                password = _read_ssh_password("%s 的 SSH 密码：" % spec["display"],
                                              timeout=90)
            except _PasswordTimeout:
                print("\n密码输入超时（90 秒），已结束。", file=sys.stderr)
                return 3
            except _PasswordAbort:
                print("\n检测到 Ctrl+Z，已结束。", file=sys.stderr)
                return 3
            except (EOFError, KeyboardInterrupt):
                print("\n已取消启动。", file=sys.stderr)
                return 3
            try:
                ssh_password = password
                remote_fs = RemoteFS(spec, password=password, prompt=False, verbose=True)
                remote_ssh = RemoteSSH(spec, password=password, prompt=False, verbose=True)
            except RemoteError as exc:
                print("ERROR: %s" % exc, file=sys.stderr)
                return 2
        else:
            try:
                # 复用预检连接做文件 SFTP；终端另开一条 SSH，避免传输阻塞 shell。
                remote_fs = RemoteFS(spec, prompt=False, verbose=False,
                                     client=status["client"], auth=status["auth"])
                remote_ssh = RemoteSSH(spec, prompt=False, verbose=False)
            except RemoteError as exc:
                try:
                    status["client"].close()
                except Exception:
                    pass
                print("ERROR: %s" % exc, file=sys.stderr)
                return 2

        if args.run_dir and not remote_fs.set_root(args.run_dir):
            print("WARNING: 远程路径 %s 无效或不是目录，使用 SSH 默认目录 %s。"
                  % (args.run_dir, remote_fs.default_root), file=sys.stderr)
        remote_ssh.root = remote_fs.root
        _CONF["remote_fs"] = remote_fs
        _CONF["remote_ssh"] = remote_ssh
        _CONF["start"] = str(remote_fs.root_local)
        _CONF["ssh_password"] = ssh_password
        _CONF["socks_ports"] = socks_ports

    if forward_mode:
        if not args.serve and not ssh_password:
            _conf = {
                "ssh": spec["spec"],
                "identity": spec.get("identity", ""),
                "server_cmd": [],
                "mode": forward_mode,
                "remote_port": args.rmt_port,
                "socket_path": args.socket if forward_mode == "unix" else None,
                "directory": remote_fs.root,
                "home": remote_fs.remote_home(),
                "no_token": bool(forward_mode == "unix" and no_token),
                "socks_ports": list(socks_ports) if socks_ports else [],
            }
            info = remote_fs.detect_remote_server()
            if not info:
                reason = getattr(remote_fs, "_render_error", "") or "未找到 mt.server"
                print("ERROR: 远端未安装可用的 mt.server：%s" % reason, file=sys.stderr)
                return 2
            _conf["server_cmd"] = info[0]
            try:
                remote_fs.close(); remote_ssh.close()
            except Exception:
                pass
            return _start_forward_background(_conf, args.port,
                                             log=_resolve_log(args.log, args.port),
                                             no_hup=args.no_hup)

        info = remote_fs.detect_remote_server()
        if not info:
            reason = getattr(remote_fs, "_render_error", "") or "未找到 mt.server"
            print("ERROR: 远端未安装可用的 mt.server：%s" % reason, file=sys.stderr)
            return 2
        server_cmd, _version = info
        channel = RemoteForwardChannel(
            spec, server_cmd, forward_mode, args.port,
            remote_port=args.rmt_port,
            socket_path=args.socket if forward_mode == "unix" else None,
            directory=remote_fs.root, password=ssh_password,
            no_token=bool(forward_mode == "unix" and no_token),
            home=remote_fs.remote_home())
        if not channel.start():
            print("ERROR: %s" % channel.error, file=sys.stderr)
            return 2
        if socks_ports:
            share = SocksShare(spec, socks_ports[0], socks_ports[1],
                               password=ssh_password, client=remote_fs.client,
                               verbose=False)
            if not share.start():
                print("ERROR: SOCKS5 共享失败：%s" % share.error, file=sys.stderr)
                channel.close()
                return 2
            _CONF["socks_share"] = share
        # 转发模式不再需要 SFTP/终端连接，关闭以免空转。
        try:
            remote_fs.close()
            remote_ssh.close()
        except Exception:
            pass
        out, _err = _term_streams()
        print("McTa 远程转发服务", file=out, flush=True)
        print("  地址    " + channel.url, file=out, flush=True)
        print("  远端    %s" % spec["display"], file=out, flush=True)
        print("  模式    %s" % ("TCP 端口转发（强制 token）" if forward_mode == "tcp"
                                else "Unix socket 转发（token %s）" % ("关闭" if no_token else "远端生成")),
              file=out, flush=True)
        if forward_mode == "tcp":
            print("  远端端口 %d" % args.rmt_port, file=out, flush=True)
        else:
            print("  远端 socket " + channel.remote_socket, file=out, flush=True)
        print("  本地端口 %d" % args.port, file=out, flush=True)
        if socks_ports:
            print("  SOCKS5  远端 %d → 本地 %d（出口本地网络）" % socks_ports,
                  file=out, flush=True)
        print("  停止    Ctrl+C；远端进程随 SSH 会话一起结束", file=out, flush=True)
        print("", file=out, flush=True)
        try:
            while channel.ready and channel.proc is not None and channel.proc.poll() is None:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n已停止", file=out, flush=True)
        finally:
            channel.close()
            _close_remote_resources()
        return 0

    # 本地运行目录：-d 指定或默认当前目录，必须是存在的目录
    if remote_fs is None and args.run_dir is not None:
        target = Path(args.run_dir).expanduser()
        try:
            target = target.resolve()
        except OSError as exc:
            print("ERROR: 无法解析目录 %s：%s" % (args.run_dir, exc), file=sys.stderr)
            return 2
        if not target.exists():
            print("ERROR: 目录不存在：%s" % target, file=sys.stderr)
            return 2
        if not target.is_dir():
            print("ERROR: 路径不是目录：%s" % target, file=sys.stderr)
            return 2
        try:
            os.chdir(str(target))
            _CONF["start"] = str(target)
        except OSError as exc:
            print("ERROR: 无法进入目录 %s：%s" % (target, exc), file=sys.stderr)
            return 2

    # 危险选项确认：-L 非回环地址、-N 无鉴权各确认一次，同时使用则需输入两次。
    # -Y/--yes 可跳过所有输入确认，适合脚本化或 CI 场景。
    # 后台子进程（--serve）由父进程拉起，这里跳过，避免重复询问。
    if os.environ.get(SKIP_CONFIRM_ENV) != "1" and not args.yes:
        if not forward_mode and not args.socket and not _is_loopback(args.host):
            if not _confirm_risk("已绑定 %s（非回环地址）：能访问该端口的人都可以读写文件并执行命令。"
                                 % args.host):
                return 3
        if no_token:
            if not _confirm_risk("已启用 -N（不校验 token）：任何能访问该端口的人都能读写文件并执行命令。"):
                return 3

    if remote_fs is not None and not forward_mode:
        warning = cache_size_warning()
        if warning:
            print("WARNING: " + warning, file=_term_streams()[1], flush=True)

    token = "" if no_token else (os.environ.get(TOKEN_ENV) or secrets.token_urlsafe(24))

    if args.socket:
        if _socket_in_use(args.socket):
            print("ERROR: Unix socket %s 正在被使用，请换一个路径或先停止该服务。"
                  % args.socket, file=sys.stderr)
            return 2
    else:
        _stop_existing(args.port)

    try:
        return _serve(args.host, args.port, token, socket_path=args.socket) if args.serve \
            else _start_background(args.host, args.port, token,
                                   log=_resolve_log(args.log, args.port),
                                   no_hup=args.no_hup, socket_path=args.socket,
                                   socks_ports=socks_ports)
    except OSError as exc:
        print("ERROR: 无法监听 %s:%d（%s）" % (args.host, args.port, exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
