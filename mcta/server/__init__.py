"""mt.server —— 本地文件与终端服务（浏览器界面）。

    mt.server                  在后台启动服务，默认 http://127.0.0.1:9068/?t=TOKEN
    mt.server -p 8080          指定端口
    mt.server -f               在当前终端直接运行，Ctrl+C 停止
    mt.server -L 0.0.0.0       监听所有网卡（需输入 yes 确认，会打印安全警告）
    mt.server -N               不启用 token（需输入 yes 确认）
    mt.server -o [PATH]        输出日志文件（默认不写，同名文件覆盖）
    mt.server -S               停止后台服务

同一端口已有 mt.server 在运行时，会先停止旧服务再启动新的；启动它的终端
关闭或退出后，后台服务会自动停止。

服务以当前用户身份运行；文件浏览/编辑跟随运行目录与终端当前目录，终端仍是完整 shell，
提供与 SSH 一致的交互式终端（xterm.js + PTY）。每次启动都会生成新的
随机 token 并写进 URL，所有请求都要校验；默认只监听回环地址，不要将
带 token 的链接分享给他人，也不要对外网开放。
"""

import argparse
import base64
import codecs
import getpass
import json
import mimetypes
import os
import platform
import queue
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from mcta import __version__, version_string

try:  # 终端只在 POSIX 上可用
    import fcntl
    import pty
    import select
    import struct
    import termios
    _HAS_PTY = True
except ImportError:  # pragma: no cover - Windows
    _HAS_PTY = False

DEFAULT_PORT = 9068
DEFAULT_HOST = "127.0.0.1"
MAX_EDIT_BYTES = 2 * 1024 * 1024
MAX_INPUT = 64 * 1024
TOKEN_COOKIE = "mcta_token"
TOKEN_ENV = "MCTA_SERVER_TOKEN"
NO_TOKEN_ENV = "MCTA_SERVER_NO_TOKEN"
ROOT_ENV = "MCTA_SERVER_ROOT"
GUARD_ENV = "MCTA_SERVER_GUARD_PID"
SKIP_CONFIRM_ENV = "MCTA_SERVER_NO_CONFIRM"
NOHUP_ENV = "MCTA_SERVER_NOHUP"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".jfif", ".gif", ".apng", ".webp", ".bmp", ".ico", ".svg", ".avif"}
PDF_EXTS = {".pdf"}
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".flac"}
VIDEO_EXTS = {".mp4", ".m4v", ".webm", ".ogv"}
MEDIA_EXTS = AUDIO_EXTS | VIDEO_EXTS
MEDIA_MIMES = {
    ".apng": "image/apng", ".avif": "image/avif", ".jfif": "image/jpeg",
    ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg",
    ".oga": "audio/ogg", ".opus": "audio/ogg", ".wav": "audio/wav",
    ".flac": "audio/flac", ".m4v": "video/mp4", ".ogv": "video/ogg",
    ".webm": "video/webm", ".pdf": "application/pdf",
}
MARKDOWN_EXTS = {".md", ".markdown"}
TABLE_EXTS = {".csv", ".tsv"}
JSON_EXTS = {".json"}
MAX_TABLE_ROWS = 2000
STRUCT_EXTS = {
    # 晶体学 / VASP / 通用坐标 / 分子
    ".cif", ".vasp", ".poscar", ".contcar", ".xyz", ".extxyz", ".xsf",
    ".pdb", ".mol", ".mol2", ".sdf", ".res", ".gen", ".traj",
    # Materials Studio
    ".xsd", ".xtd",
    # CASTEP
    ".cell", ".castep", ".geom",
    # SIESTA
    ".xv",
    # DMol3
    ".car", ".arc",
    # Gaussian
    ".gjf", ".com",
    # VASP 轨迹
    ".xdatcar", ".outcar",
    # GROMACS / LAMMPS / CP2K / wannier90
    ".gro", ".dump", ".dcd", ".wout",
    # 其他通用格式
    ".cjson", ".struct", ".rmc6f", ".qbox", ".mustem", ".magres",
}
STRUCT_NAMES = {"POSCAR", "CONTCAR", "SPOSCAR", "XDATCAR", "OUTCAR", "GEOMETRY.IN"}
DENSITY_NAMES = {"CHGCAR", "CHG", "LOCPOT"}
DENSITY_PREFIXES = ("CHGCAR", "CHG", "LOCPOT")  # CHGCAR-big、LOCPOT-slab 等
STRUCT_PREFIXES = ("POSCAR-",)  # POSCAR-unitcell、POSCAR-12345 等
LAMMPS_DATA_EXTS = {".data", ".lmp", ".lammps"}  # 按文件内容判断，不直接当结构
MAX_STRUCT_BYTES = 32 * 1024 * 1024
MAX_DENSITY_BYTES = 128 * 1024 * 1024
MAX_DENSITY_POINTS = 4000000
MAX_STRUCT_FRAMES = 300  # 轨迹播放帧数上限
MAX_TRAJ_ATOMS = 2000000  # 轨迹所有帧的原子总数上限
ASSET_DIR = Path(__file__).resolve().parent

_TERMINALS = {}
_TERMINALS_LOCK = threading.Lock()


def _clean_sid(value, fallback="default"):
    """把请求里的窗口会话 ID 收敛成安全的字典键；非法值回退到 default。"""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    value = str(value or "").strip()
    if 1 <= len(value) <= 64 and all(ch.isalnum() or ch in "-_" for ch in value):
        return value
    return fallback


# ------------------------------------------------------------------ 通用 ---
def _state_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(str(Path.home()), ".cache")
    path = Path(base) / "mcta"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pid_path(port):
    return _state_dir() / ("server-%d.pid" % port)


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


def _is_structure(path):
    # *.json（含 CHGCAR_mcta.json / LOCPOT_mcta.json 这类视图存档与日志）
    # 一律按文本处理；不能因 CHGCAR_/LOCPOT_ 前缀误判成 VASP 密度结构。
    if path.suffix.lower() in JSON_EXTS:
        return False
    if path.suffix.lower() in STRUCT_EXTS:
        return True
    if path.suffix.lower() in LAMMPS_DATA_EXTS:
        return _lammps_data_style(path) is not None
    name = path.name.upper()
    if name in STRUCT_NAMES or name in DENSITY_NAMES or name.startswith(STRUCT_PREFIXES):
        return True
    # 密度前缀匹配
    for prefix in DENSITY_PREFIXES:
        if name == prefix or name.startswith(prefix + "-") or name.startswith(prefix + "_"):
            return True
    return False


def _is_vasp_density(path):
    if path.suffix.lower() in JSON_EXTS:
        return False
    name = path.name.upper()
    if name in DENSITY_NAMES:
        return True
    for prefix in DENSITY_PREFIXES:
        if name.startswith(prefix + "-") or name.startswith(prefix + "_"):
            return True
    return False


def _read_vasp_density(path):
    """读取 VASP 标量网格；电荷密度换算为 e/Å³，势函数保持原值。

    返回 (atoms, groups)，其中 groups 为 [(label, ndarray), ...]。
    CHGCAR/CHG 自旋极化时第一组为总电荷密度、第二组为自旋密度（磁化密度）。
    LOCPOT 可能含多组势函数。
    """
    import numpy as np
    from pathlib import Path
    from ase.io.vasp import read_vasp_configuration

    path = Path(path)
    name = path.name.upper()
    is_charge = name == "CHGCAR" or name.startswith("CHGCAR-") or name.startswith("CHGCAR_") or \
                name == "CHG" or name.startswith("CHG-") or name.startswith("CHG_")
    is_locpot = name == "LOCPOT" or name.startswith("LOCPOT-") or name.startswith("LOCPOT_")
    is_charge = is_charge and not is_locpot  # CHGCAR-big > LOCPOT-slab 互不影响
    with open(path, "r") as fh:
        atoms = read_vasp_configuration(fh)
        groups = []
        seen_shape = None
        group_index = 0
        while True:
            # 跳过空行直到遇到网格尺寸行
            line = fh.readline()
            while line and not line.strip():
                line = fh.readline()
            if not line:
                break
            fields = line.split()
            if len(fields) != 3:
                raise ValueError("无效的密度网格尺寸")
            try:
                shape = tuple(int(value) for value in fields)
            except ValueError as exc:
                raise ValueError("无效的密度网格尺寸") from exc
            if any(value <= 0 for value in shape):
                raise ValueError("密度网格尺寸必须为正整数")
            if seen_shape is None:
                seen_shape = shape
            elif shape != seen_shape:
                # 不同 shape 停止读取
                break
            count = shape[0] * shape[1] * shape[2]
            if count > MAX_DENSITY_POINTS:
                raise ValueError("密度网格过大（上限 %d 点）" % MAX_DENSITY_POINTS)
            values = []
            while len(values) < count:
                line = fh.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                try:
                    values.extend(float(value) for value in line.split())
                except ValueError as exc:
                    raise ValueError("密度网格包含无效数值") from exc
            if len(values) < count:
                break
            data = np.asarray(values[:count], dtype=float).reshape(shape, order="F")
            if is_charge:
                volume = abs(float(atoms.cell.volume))
                if not volume:
                    raise ValueError("晶胞体积为零，无法换算电荷密度")
                data = data / volume
            if is_charge:
                label = "总电荷密度" if group_index == 0 else "自旋密度"
            else:
                label = "势函数 %d" % (group_index + 1) if group_index > 0 else "势函数"
            groups.append((label, data))
            group_index += 1
            if group_index >= 4:
                break
    if not groups:
        raise ValueError("文件不包含有效密度网格")
    return atoms, groups


def _density_options(data, label):
    """根据有效数据生成等值面默认值及滑杆量程。

    label 可为 '总电荷密度'（非负、默认 0.02）、'自旋密度'（允许负值、默认中位数）、
    '势函数'（允许负值、默认中位数）。
    """
    import numpy as np

    finite = data[np.isfinite(data)]
    if not finite.size:
        raise ValueError("密度网格没有有限数值")
    minimum = float(finite.min())
    maximum = float(finite.max())
    if minimum == maximum:
        delta = max(abs(minimum) * 0.1, 0.001)
        minimum, maximum = minimum - delta, maximum + delta
    is_total_charge = label == "总电荷密度"
    if is_total_charge:
        lower = max(0.0, minimum)
        upper = float(np.quantile(finite, 0.99))
        value = 0.02
    else:
        lower = float(np.quantile(finite, 0.01))
        upper = float(np.quantile(finite, 0.99))
        value = float(np.median(finite))
    if upper <= lower:
        lower, upper = minimum, maximum
    value = min(max(value, lower), upper)
    step = (upper - lower) / 1000
    value = lower + round((value - lower) / step) * step
    return {"min": lower, "max": upper, "step": step, "value": value}


def _lammps_data_style(path):
    """识别 LAMMPS data 文件并返回其 Atoms 段风格；不是 data 文件返回 None。"""
    try:
        with open(path, "r", errors="replace") as fh:
            head = fh.read(65536)
    except OSError:
        return None
    if "LAMMPS data file" not in head:
        return None
    lines = head.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("Atoms"):
            continue
        if "#" in stripped:
            style = stripped.split("#", 1)[1].strip().split()[0].lower()
            if style:
                return style
        # 没有风格注释时按坐标行列数推断
        for row in lines[index + 1:]:
            fields = row.split()
            if not fields:
                continue
            count = len(fields)
            if count >= 8:
                return "bond"
            if count == 7:
                return "full"
            if count == 6:
                return "charge"
            return "atomic"
        return "atomic"
    return None


def _read_atoms(path):
    """读取结构文件；LAMMPS data 文件按 Atoms 段风格显式解析。"""
    from ase.io import read as ase_read

    style = _lammps_data_style(path)
    if style is None:
        return ase_read(str(path), index=0)
    last = None
    for candidate in (style, "atomic", "full", "charge", "molecular", "bond"):
        try:
            return ase_read(str(path), index=0, format="lammps-data", atom_style=candidate)
        except Exception as exc:  # 风格不符时换下一种再试
            last = exc
    raise last


def _read_frames(path, limit):
    """读取轨迹的前 limit 帧；单帧结构返回只含 1 帧的列表。"""
    from ase.io import read as ase_read

    style = _lammps_data_style(path)
    kwargs = {"format": "lammps-data", "atom_style": style} if style else {}
    try:
        seq = ase_read(str(path), index=slice(0, limit), **kwargs)
    except Exception:
        seq = ase_read(str(path), index=":", **kwargs)[:limit]
    if not isinstance(seq, list):
        seq = [seq]
    return seq


def _kind(path):
    if path.is_dir():
        return "dir"
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTS:
        return "image"
    if suffix in PDF_EXTS:
        return "pdf"
    if suffix in MEDIA_EXTS:
        return "media"
    if _is_structure(path):
        return "structure"
    return "file"


def _printable_ratio(text):
    """文本中可打印字符（含常见空白）的占比，用于区分宽字符文本与二进制。"""
    if not text:
        return 0.0
    good = 0
    for ch in text:
        if ch in "\r\n\t\f\v" or ch.isprintable():
            good += 1
    return good / len(text)


def _decode_utf16(data, le=True):
    """尝试把数据按 UTF-16（UCS-2）解码并验证是否为文本，成功返回文本否则 None。"""
    enc = "utf-16-le" if le else "utf-16-be"
    try:
        text = data.decode(enc)
    except (UnicodeDecodeError, ValueError):
        return None
    # 去掉可能存在的 BOM 残留，再按可打印比例判断
    text = text.lstrip("\ufeff")
    if _printable_ratio(text) >= 0.9:
        return text
    return None


def _decode(data):
    """把字节解码为文本；优先 BOM，再 UTF-8 / ANSI，最后尝试无 BOM 的 UCS-2。

    返回解码后的文本，无法识别为文本时返回 None。
    """
    if not data:
        return ""
    # 1) BOM 优先：先长后短，避免 UTF-32 的 FF FE 00 00 被 UTF-16LE 的 FF FE 抢先
    for bom, enc in (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if data.startswith(bom):
            try:
                return data.decode(enc).lstrip("\ufeff")
            except (UnicodeDecodeError, ValueError):
                return None
    # 2) 无 BOM：先按 UTF-8 解码；NUL 虽是合法 UTF-8 字符，但正常文本几乎不含它，
    #    因此 UTF-8 成功但含 NUL 时也继续尝试 UCS-2，避免把 UTF-16 误判成带 NUL 的文本。
    utf8_text = None
    try:
        utf8_text = data.decode("utf-8")
        if "\x00" not in utf8_text:
            return utf8_text
    except UnicodeDecodeError:
        pass
    # 3) 含 NUL 字节时，优先按无 BOM 的 UCS-2 解码（小端优先，符合多数 Windows 文本）
    if b"\x00" in data[:4096] and len(data) % 2 == 0:
        decoded = _decode_utf16(data, le=True) or _decode_utf16(data, le=False)
        if decoded is not None:
            return decoded
    # 4) 再按 ANSI(GB18030) 解码
    if utf8_text is not None:
        return utf8_text
    try:
        return data.decode("gb18030")
    except UnicodeDecodeError:
        return None


def _mtime(path):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))
    except OSError:
        return ""


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


# ------------------------------------------------------------------ 认证 ---
def _token_matches(given):
    """校验启动时生成的随机 token（每个进程一份，重启即更换）。"""
    if _CONF.get("no_token"):
        return True
    expected = _CONF.get("token") or ""
    return bool(given) and bool(expected) and secrets.compare_digest(str(given), expected)


# ------------------------------------------------------------------ 终端 ---
class _Terminal:
    def __init__(self, cwd, rows, cols):
        self.subs = []
        self.subs_lock = threading.Lock()
        self.backlog = bytearray()
        self.alive = True
        self.pid = None
        self.master = None
        if not _HAS_PTY:
            self.alive = False
            return

        pid, master = pty.fork()
        if pid == 0:  # 子进程
            try:
                os.chdir(str(cwd))
                env = os.environ.copy()
                env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor"})
                shell = env.get("SHELL") or "/bin/bash"
                os.execvpe(shell, [shell, "-i"], env)
            finally:
                os._exit(1)

        self.pid = pid
        self.master = master
        self.resize(rows, cols)
        threading.Thread(target=self._reader, daemon=True).start()

    def _publish(self, data):
        """把输出广播给所有订阅者，并记入回放缓存。"""
        with self.subs_lock:
            if data:
                self.backlog.extend(data)
                if len(self.backlog) > 262144:
                    del self.backlog[:-262144]
            subs = list(self.subs)
        for sub in subs:
            try:
                sub.put_nowait(data)
            except queue.Full:
                pass

    def subscribe(self):
        sub = queue.Queue(maxsize=8192)
        with self.subs_lock:
            self.subs.append(sub)
            snapshot = bytes(self.backlog)
        if snapshot:
            # 补发此前输出，新页面打开时能立即看到已有提示符与内容
            try:
                sub.put_nowait(snapshot)
            except queue.Full:
                pass
        return sub

    def unsubscribe(self, sub):
        with self.subs_lock:
            try:
                self.subs.remove(sub)
            except ValueError:
                pass

    def _reader(self):
        master = self.master
        while self.alive:
            try:
                ready, _, _ = select.select([master], [], [], 0.5)
            except (OSError, ValueError, TypeError):
                break
            if not ready:
                continue
            try:
                data = os.read(master, 65536)
            except OSError:
                break
            if not data:
                break
            self._publish(data)
        self.alive = False
        self._publish(b"")

    def write(self, data):
        if self.master is None:
            return
        os.write(self.master, data)

    def resize(self, rows, cols):
        if self.master is None:
            return
        try:
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def cwd(self):
        """读取 shell 进程的当前目录（Linux /proc）。"""
        if not self.pid:
            return None
        try:
            return os.readlink("/proc/%d/cwd" % self.pid)
        except OSError:
            return None

    def close(self):
        self.alive = False
        if self.master is not None:
            try:
                os.close(self.master)
            except OSError:
                pass
            self.master = None
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except OSError:
                pass
            self.pid = None


_CONF = {
    "token": "",
    "no_token": False,
    "user": getpass.getuser(),
    # 页面起始目录：运行 mt.server 的目录（后台模式由父进程经环境变量传入）
    "start": os.environ.get(ROOT_ENV) or str(Path.cwd().resolve()),
}

def _terminal_for(rows, cols, sid="default"):
    if not _HAS_PTY:
        return None
    sid = _clean_sid(sid)
    with _TERMINALS_LOCK:
        term = _TERMINALS.get(sid)
        if term and term.alive:
            term.resize(rows, cols)
            return term
        if term:
            term.close()
        # 防止长期运行后残留大量已退出的会话。
        if len(_TERMINALS) >= 64:
            for key in [k for k, t in list(_TERMINALS.items()) if not t.alive]:
                try:
                    _TERMINALS.pop(key).close()
                except Exception:
                    pass
        if len(_TERMINALS) >= 64 and _TERMINALS:
            key = next(iter(_TERMINALS))
            try:
                _TERMINALS.pop(key).close()
            except Exception:
                pass
        start = Path(_CONF["start"]).resolve()
        term = _Terminal(str(start), rows, cols)
        _TERMINALS[sid] = term
        return term


# ------------------------------------------------------------------ 服务 ---
def _make_handler():

    class Handler(BaseHTTPRequestHandler):
        server_version = "McTaServer/" + __version__
        protocol_version = "HTTP/1.1"

        # ---------------------------------------------------------- 基础 ---
        def _send(self, body, content_type, status=200, headers=None):
            extra = list(headers or [])
            names = {name.lower() for name, _ in extra}
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if "x-frame-options" not in names:
                self.send_header("X-Frame-Options", "DENY")
            for name, value in extra:
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

        def _json(self, data, status=200, headers=None):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._send(body, "application/json; charset=utf-8", status, headers)

        def _send_file(self, target, content_type, inline=False, extra=None):
            """发送本地文件，支持 Range（音视频拖动进度、PDF 分页加载）。"""
            size = target.stat().st_size
            headers = list(extra or [])
            disp = "inline" if inline else "attachment"
            headers.append(("Content-Disposition",
                            "%s; filename*=UTF-8''%s" % (disp, quote(target.name))))
            start, end, status = 0, max(0, size - 1), 200
            rng = (self.headers.get("Range") or "").strip()
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", rng) if rng else None
            if match:
                first, last = match.groups()
                if first or last:
                    if not first:
                        start = max(0, size - int(last))
                        end = size - 1
                    else:
                        start = int(first)
                        end = int(last) if last else size - 1
                    if start >= size or end < start:
                        self._send(b"", "application/octet-stream", 416, [
                            ("Content-Range", "bytes */%d" % size),
                        ])
                        return
                    end = min(end, size - 1)
                    status = 206
                    headers.append(("Content-Range", "bytes %d-%d/%d" % (start, end, size)))
            names = {name.lower() for name, _ in headers}
            length = 0 if size == 0 else end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if "x-frame-options" not in names:
                self.send_header("X-Frame-Options", "DENY")
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            if self.command == "HEAD":
                return
            try:
                with target.open("rb") as fh:
                    fh.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = fh.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except OSError:
                pass

        def _error(self, message, status=400):
            self._json({"error": message}, status)

        def _body(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 8 * 1024 * 1024:
                    raise ValueError("请求体过大")
                return json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                raise ValueError("请求体不是合法 JSON")

        def _cookie_token(self):
            raw = self.headers.get("Cookie", "")
            for part in raw.split(";"):
                name, _, value = part.strip().partition("=")
                if name == TOKEN_COOKIE and value:
                    return value
            return ""

        def _authorized(self, query=None):
            given = ((query or {}).get("t") or [""])[0] or self._cookie_token()
            return _token_matches(given)

        def _forbidden(self):
            self._send(
                "未授权：请使用 mt.server 启动时打印的带 token 的链接访问。".encode("utf-8"),
                "text/plain; charset=utf-8", 403)

        def _root_dir(self):
            """页面起始目录：运行 mt.server 的目录。"""
            return Path(_CONF["start"]).resolve()

        def _resolve(self, rel):
            """解析到运行目录/终端目录及其上级；.. 与符号链接逃逸一律拒绝。"""
            raw = (rel or "").replace("\\", "/")
            root = self._root_dir()
            bases = [root]
            term_cwd = None
            term = _TERMINALS.get(getattr(self, "_sid", "default"))
            if term:
                cwd = term.cwd()
                if cwd:
                    term_cwd = Path(cwd).resolve()
                    bases.append(term_cwd)

            def allowed(path):
                for base in bases:
                    try:
                        path.relative_to(base)
                        return True
                    except ValueError:
                        continue
                # 终端目录的上级（如 /mnt）也放行，保证面包屑可以逐级返回；
                # 文件系统根 / 不放行，避免把整块磁盘都纳入浏览范围。
                if term_cwd is not None and path != Path("/"):
                    try:
                        term_cwd.relative_to(path)
                        return True
                    except ValueError:
                        pass
                return False

            if raw.startswith("/"):
                # 绝对路径先看是否落在允许目录内；否则兼容历史行为，
                # 按运行目录下的相对路径解释（旧前端会传 /inside.txt）。
                real = Path(raw).resolve()
                target = real if allowed(real) else (root / raw.lstrip("/")).resolve()
            else:
                target = (root / raw).resolve() if raw else root
            # resolve() 已展开 .. 与符号链接，这里做最终包含性校验。
            if not allowed(target):
                raise ValueError("路径必须位于运行目录或终端当前目录内")
            return target

        def _rel(self, path):
            try:
                rel = path.relative_to(self._root_dir()).as_posix()
            except ValueError:
                return path.as_posix()
            return "" if rel == "." else rel

        def log_message(self, fmt, *args):
            line = fmt % args
            # URL 里的 ?t=TOKEN 是访问凭据，绝不能原样落进日志。
            token = _CONF.get("token") or ""
            if token:
                line = line.replace(token, "***")
                line = line.replace(quote(token), "***")
            sys.stderr.write("[mt.server] " + line + "\n")

        # ------------------------------------------------------------ GET ---
        def do_GET(self):
            parsed = urlparse(self.path)
            route = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            self._sid = _clean_sid(query.get("sid"))
            if not self._authorized(query):
                self._forbidden()
                return

            if route in ("/", "/index.html"):
                headers = []
                if _CONF.get("token"):
                    headers.append(("Set-Cookie",
                                    "%s=%s; Path=/; HttpOnly; SameSite=Strict"
                                    % (TOKEN_COOKIE, _CONF["token"])))
                self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8",
                           headers=headers)
                return
            if route == "/favicon.ico":
                self._send(b"", "image/x-icon", 204)
                return
            if route.startswith("/assets/"):
                self._asset(route[len("/assets/"):])
                return
            if route == "/api/info":
                self._info()
                return
            if route == "/api/list":
                self._list((query.get("path") or [""])[0])
                return
            if route == "/api/file":
                self._file((query.get("path") or [""])[0])
                return
            if route == "/api/structure":
                frames = (query.get("frames") or [""])[0] in ("1", "true", "yes")
                self._structure((query.get("path") or [""])[0], frames)
                return
            if route == "/raw":
                self._raw((query.get("path") or [""])[0])
                return
            if route == "/api/term/stream":
                self._term_stream(query)
                return
            if route == "/api/term/cwd":
                self._term_cwd(query)
                return
            self._error("未知路径", 404)

        def _asset(self, name):
            if name not in ("xterm.js", "xterm.css", "3dmol-min.js"):
                self._error("资源不存在", 404)
                return
            path = ASSET_DIR / name
            if not path.is_file():
                self._error("资源缺失", 404)
                return
            content_type = "text/javascript; charset=utf-8" if name.endswith(".js") else "text/css; charset=utf-8"
            self._send(path.read_bytes(), content_type)

        def _info(self):
            self._json({
                "root": str(self._root_dir()),
                "user": _CONF["user"],
                "version": __version__,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "terminal": _HAS_PTY,
            })

        def _list(self, rel):
            try:
                target = self._resolve(rel)
            except ValueError as exc:
                self._error(str(exc), 403)
                return
            if not target.is_dir():
                self._error("不是目录", 404)
                return

            rows = []
            try:
                with os.scandir(str(target)) as scan:
                    for item in scan:
                        try:
                            stat = item.stat()
                            is_dir = item.is_dir()
                        except OSError:
                            continue
                        child = Path(item.path)
                        kind = "dir" if is_dir else _kind(child)
                        rows.append((not is_dir, item.name.lower(), {
                            "name": item.name,
                            "path": self._rel(child),
                            "dir": is_dir,
                            "kind": kind,
                            "mediaType": ("audio" if child.suffix.lower() in AUDIO_EXTS else "video")
                                if kind == "media" else None,
                            "size": None if is_dir else stat.st_size,
                            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                            "ts": stat.st_mtime,
                        }))
            except OSError as exc:
                self._error("无法读取目录：%s" % exc, 500)
                return
            rows.sort(key=lambda row: (row[0], row[1]))
            entries = [row[2] for row in rows]

            parent = "" if target == self._root_dir() else self._rel(target.parent)
            self._json({
                "root": str(self._root_dir()),
                "path": self._rel(target),
                "parent": parent,
                "entries": entries,
            })

        def _file(self, rel):
            try:
                target = self._resolve(rel)
            except ValueError as exc:
                self._error(str(exc), 403)
                return
            if not target.is_file():
                self._error("文件不存在", 404)
                return

            size = target.stat().st_size
            info = {"path": self._rel(target), "name": target.name, "size": size, "mtime": _mtime(target)}
            kind = _kind(target)
            if kind in ("pdf", "media"):
                info.update({
                    "kind": kind,
                    "mediaType": "audio" if target.suffix.lower() in AUDIO_EXTS else "video",
                    "url": "/raw?path=" + quote(self._rel(target)),
                })
                self._json(info)
                return
            if kind == "image":
                info.update({"kind": "image", "url": "/raw?path=" + quote(self._rel(target))})
                self._json(info)
                return
            if size > MAX_EDIT_BYTES:
                info.update({"kind": "binary", "url": "/raw?path=" + quote(self._rel(target))})
                self._json(info)
                return

            data = target.read_bytes()
            text = _decode(data)
            if text is None:
                info.update({"kind": "binary", "url": "/raw?path=" + quote(self._rel(target))})
            else:
                info.update({"kind": "text", "text": text})
            self._json(info)

        def _structure(self, rel, frames=False):
            try:
                target = self._resolve(rel)
            except ValueError as exc:
                self._error(str(exc), 403)
                return
            if not target.is_file():
                self._error("文件不存在", 404)
                return
            if not _is_structure(target):
                self._error("不是可识别的结构文件", 400)
                return
            try:
                size = target.stat().st_size
            except OSError as exc:
                self._error("无法读取文件：%s" % exc, 500)
                return
            density = _is_vasp_density(target)
            size_limit = MAX_DENSITY_BYTES if density else MAX_STRUCT_BYTES
            if size > size_limit:
                label = "密度" if density else "结构"
                self._error("%s文件过大（上限 %d MB）" % (label, size_limit // 1024 // 1024), 413)
                return
            try:
                from ase.io import write as ase_write
                import io
                if density:
                    from ase.io.cube import write_cube
                    from tempfile import TemporaryFile
                    density_atoms, density_groups = _read_vasp_density(target)
                    seq, truncated = [density_atoms], False
                elif frames:
                    seq = _read_frames(target, MAX_STRUCT_FRAMES + 1)
                    if not seq:
                        raise ValueError("轨迹中没有可用帧")
                    truncated = len(seq) > MAX_STRUCT_FRAMES
                    seq = seq[:MAX_STRUCT_FRAMES]
                    # 按总原子数再收一次，避免超大体系占用过多内存
                    total, keep = 0, 0
                    for item in seq:
                        if total + len(item) > MAX_TRAJ_ATOMS:
                            truncated = True
                            break
                        total += len(item)
                        keep += 1
                    seq = seq[:keep] or seq[:1]
                else:
                    seq, truncated = [_read_atoms(target)], False
                first = seq[0]
                buf = io.BytesIO()
                ase_write(buf, first, format="cif")
                cif = buf.getvalue().decode("utf-8", "replace")
                payload = {
                    "path": self._rel(target),
                    "name": target.name,
                    "formula": first.get_chemical_formula(),
                    "natoms": len(first),
                    "size": size,
                    "mtime": _mtime(target),
                    "cif": cif,
                    "nframes": len(seq),
                    "truncated": bool(truncated),
                }
                if bool(first.pbc.any()):
                    payload["cell"] = first.cell[:].tolist()
                if density:
                    from ase.io.cube import write_cube
                    from tempfile import TemporaryFile
                    group_list = []
                    first_cube = None
                    for idx, (glabel, gdata) in enumerate(density_groups):
                        with TemporaryFile(mode="w+", encoding="utf-8") as cube_buf:
                            write_cube(cube_buf, first, data=gdata, comment="%s-%s" % (target.name, glabel))
                            cube_buf.seek(0)
                            cube_text = cube_buf.read()
                        group_list.append({
                            "label": glabel,
                            "cube": cube_text,
                            "options": _density_options(gdata, glabel),
                        })
                    payload["densities"] = group_list
                if frames and len(seq) > 1:
                    xyz_buf = io.StringIO()  # xyz 写入器按文本写，不能用 BytesIO
                    ase_write(xyz_buf, seq, format="xyz")
                    payload["xyz"] = xyz_buf.getvalue()
            except ImportError:
                self._error("缺少 ase，无法解析结构", 500)
                return
            except Exception as exc:
                detail = str(exc)
                if not detail or type(exc).__name__ in ("AssertionError", "StopIteration"):
                    detail = "文件内容可能不是有效的结构"
                self._error("无法解析结构：%s" % detail, 400)
                return
            self._json(payload)

        def _raw(self, rel):
            try:
                target = self._resolve(rel)
            except ValueError as exc:
                self._error(str(exc), 403)
                return
            if not target.is_file():
                self._error("文件不存在", 404)
                return

            suffix = target.suffix.lower()
            content_type = MEDIA_MIMES.get(suffix) or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            inline = (content_type.startswith(("image/", "audio/", "video/"))
                      or content_type == "application/pdf")
            extra = None
            if content_type == "application/pdf":
                # 内置 PDF 查看器需要被同源页面嵌入；其它响应仍保持 DENY。
                extra = [("X-Frame-Options", "SAMEORIGIN")]
            self._send_file(target, content_type, inline=inline, extra=extra)

        def _term_cwd(self, query):
            term = _TERMINALS.get(_clean_sid(query.get("sid")))
            self._json({
                "cwd": term.cwd() if term else None,
                "base": str(self._root_dir()),
            })

        def _term_stream(self, query):
            try:
                rows = max(4, min(200, int((query.get("rows") or ["30"])[0])))
                cols = max(20, min(500, int((query.get("cols") or ["100"])[0])))
            except ValueError:
                rows, cols = 30, 100
            term = _terminal_for(rows, cols, _clean_sid(query.get("sid")))
            if term is None:
                self._error("当前平台不支持交互式终端", 501)
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

            sub = term.subscribe()
            try:
                while True:
                    try:
                        chunk = sub.get(timeout=15)
                    except queue.Empty:
                        try:
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                        except OSError:
                            return
                        continue
                    if not chunk:
                        try:
                            self.wfile.write(b"data: \n\n")
                            self.wfile.flush()
                        except OSError:
                            pass
                        return
                    payload = base64.b64encode(chunk).decode("ascii")
                    try:
                        self.wfile.write(("data: %s\n\n" % payload).encode("ascii"))
                        self.wfile.flush()
                    except OSError:
                        return
            finally:
                term.unsubscribe(sub)

        # ----------------------------------------------------------- POST ---
        def do_POST(self):
            parsed = urlparse(self.path)
            route = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            self._sid = _clean_sid(query.get("sid"))
            if not self._authorized(query):
                self._forbidden()
                return

            if route == "/api/file":
                self._save()
            elif route == "/api/rename":
                self._rename()
            elif route == "/api/delete":
                self._delete()
            elif route == "/api/new":
                self._new_file()
            elif route == "/api/newdir":
                self._new_dir()
            elif route == "/api/term/input":
                self._term_input()
            elif route == "/api/term/resize":
                self._term_resize()
            else:
                self._error("未知路径", 404)

        def _save(self):
            try:
                payload = self._body()
                rel = str(payload.get("path") or "")
                text = payload.get("text")
                if not rel or not isinstance(text, str):
                    raise ValueError("缺少 path 或 text")
                target = self._resolve(rel)
                if target.is_dir():
                    raise ValueError("目标是目录")
                if not target.parent.is_dir():
                    raise ValueError("上级目录不存在")
            except ValueError as exc:
                self._error(str(exc), 400)
                return

            try:
                target.write_text(text, encoding="utf-8")
            except OSError as exc:
                self._error("保存失败：%s" % exc, 500)
                return
            self._json({"ok": True, "path": self._rel(target),
                        "size": target.stat().st_size, "mtime": _mtime(target)})

        def _rename(self):
            try:
                payload = self._body()
                rel = str(payload.get("path") or "")
                name = str(payload.get("name") or "").strip()
                if not rel or not name:
                    raise ValueError("缺少 path 或 name")
                if name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
                    raise ValueError("名称不能包含路径分隔符")
                if any(c in name for c in "<>'\""):
                    raise ValueError("名称不能包含 < > ' \" 等 HTML 特殊字符")
                source = self._resolve(rel)
                if not source.exists():
                    raise ValueError("文件不存在")
                target = source.parent / name
                if target == source:
                    self._json({"ok": True, "path": self._rel(source), "name": source.name})
                    return
                if target.exists():
                    raise ValueError("同名文件已存在")
                source.rename(target)
            except ValueError as exc:
                self._error(str(exc), 400)
                return
            except OSError as exc:
                self._error("重命名失败：%s" % exc, 500)
                return
            self._json({"ok": True, "path": self._rel(target), "name": target.name})

        def _delete(self):
            import shutil
            try:
                payload = self._body()
                rel = str(payload.get("path") or "")
                if not rel:
                    raise ValueError("缺少 path")
                target = self._resolve(rel)
                if not target.exists():
                    raise ValueError("路径不存在")
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            except ValueError as exc:
                self._error(str(exc), 400)
                return
            except OSError as exc:
                self._error("删除失败：%s" % exc, 500)
                return
            self._json({"ok": True})

        def _new_file(self):
            try:
                payload = self._body()
                rel = str(payload.get("path") or "")
                name = str(payload.get("name") or "").strip()
                text = payload.get("text")
                if not isinstance(text, str):
                    text = ""
                if not name:
                    raise ValueError("缺少文件名")
                if name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
                    raise ValueError("名称不能包含路径分隔符")
                if any(c in name for c in "<>'\""):
                    raise ValueError("名称不能包含 < > ' \" 等 HTML 特殊字符")
                folder = self._resolve(rel)
                if not folder.is_dir():
                    raise ValueError("目录不存在")
                target = folder / name
                if target.exists():
                    raise ValueError("同名文件已存在")
            except ValueError as exc:
                self._error(str(exc), 400)
                return
            try:
                target.write_text(text, encoding="utf-8")
            except OSError as exc:
                self._error("创建失败：%s" % exc, 500)
                return
            self._json({"ok": True, "path": self._rel(target), "name": target.name,
                        "size": target.stat().st_size, "mtime": _mtime(target)})

        def _new_dir(self):
            try:
                payload = self._body()
                rel = str(payload.get("path") or "")
                name = str(payload.get("name") or "").strip()
                if not name:
                    raise ValueError("缺少目录名")
                if name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
                    raise ValueError("名称不能包含路径分隔符")
                if any(c in name for c in "<>'\""):
                    raise ValueError("名称不能包含 < > ' \" 等 HTML 特殊字符")
                folder = self._resolve(rel)
                if not folder.is_dir():
                    raise ValueError("目录不存在")
                target = folder / name
                if target.exists():
                    raise ValueError("同名项已存在")
            except ValueError as exc:
                self._error(str(exc), 400)
                return
            try:
                target.mkdir()
            except OSError as exc:
                self._error("创建失败：%s" % exc, 500)
                return
            self._json({"ok": True, "path": self._rel(target), "name": target.name})

        def _term_input(self):
            try:
                payload = self._body()
                raw = base64.b64decode(str(payload.get("data") or ""), validate=True)
                if len(raw) > MAX_INPUT:
                    raise ValueError("输入过大")
            except (ValueError, TypeError):
                self._error("无效输入", 400)
                return

            with _TERMINALS_LOCK:
                term = _TERMINALS.get(_clean_sid(payload.get("sid")))
            if not term or not term.alive:
                self._error("终端未启动", 409)
                return
            try:
                term.write(raw)
            except OSError as exc:
                self._error("终端不可写：%s" % exc, 500)
                return
            self._json({"ok": True})

        def _term_resize(self):
            try:
                payload = self._body()
                rows = max(4, min(200, int(payload.get("rows") or 30)))
                cols = max(20, min(500, int(payload.get("cols") or 100)))
            except (ValueError, TypeError):
                self._error("无效尺寸", 400)
                return
            with _TERMINALS_LOCK:
                term = _TERMINALS.get(_clean_sid(payload.get("sid")))
            if term:
                term.resize(rows, cols)
            self._json({"ok": True})

    return Handler


# ------------------------------------------------------------------ 页面 ---
PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%23f1f4f9'/%3E%3Ctext x='32' y='45' text-anchor='middle' font-family='Arial,Helvetica,sans-serif' font-size='36' font-weight='700' fill='%23e0553d'%3EM%3C/text%3E%3C/svg%3E">
<title>McTa 文件服务</title>
<link rel="stylesheet" href="/assets/xterm.css">
<style>
  @font-face{font-family:"McTa Wordmark";src:url("data:font/woff2;base64,d09GMgABAAAAAALYABAAAAAABRAAAAJ9AAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAGhYbIBwqBmA/U1RBVCoATBEICoM8gnwBNgIkAxQLDAAEIAU+ByAMBxusA1FUDHYhPhbjmBSHxp44ETzwdtn783eCFWYjewNWOZBt0J2gokIFsbtKQ/T9iXsvP5lnAYllEkhBOl4taIHqBaoUAArPv7fnzTzxEO+wz8/eLE2jUSfkWbbj/UADLY0inUjqzVSJxLWvRegBCDADgCJiiIDRRgTi0dDWS4AB6DoAIMDoJAnF4md9T1wyjyCjYt1QG5VbqCg/ZRBopT7iRY5oItLCz9UOddezj3Ymy4W6Buos2gABKLu0gCikiBZwIyAM5TN9xhIBUAQQs3ILAAUkuJECbgzugFEr5UkvE5ms65Au6pf0M/oBff8DRcjZvbABqABG8Idx4AoAYAAAoUxyBN5ZHXZjgmnkhFA3njSNBs80zt5pGj2OYcMxo94lzqA2ZFaipC2ZqahZxp/ZnKb2E0cePVLCjx+bRh8+xLjhwYP+0c5C5yopHgrghhUDfWNeJ+Wbd8VtuqLd86FefSd161XP4d3uB9u0l9ph7wst4k/RoqisRX8itBfew9pPj/ZS8+SpnsCw6F+KX57S0Qp5OuMpGaJPeU54RumdJyiXzYubatb4fE1r1zR1dKxuouJL9Gnobt5Qri8rvTe/YIM6uTmdWRm9BfkAIUe/dlfb7pzZHfu6vY8u2bmmqWGNr6t+7coGX+nEtDmvF4Y91V7K5tz2jNSe4oK0Hl9WfmxV11/nbUvOy8YaABCADHnb59vjHbaV/Q6Q8gvAo6SzwQCf46I+YtP/ykXSAiQWBSD4Ul/IPzbrtAghIqHWQuLlI6Yom7HVQSqUISoQoLohAYRYky6kjEBKkyYEzDpSKg01zGcOUxhgKjOZzgyWIAHQd5EDxteE/j1nGAcAAAA=") format("woff2");font-style:normal;font-weight:700 900;font-display:swap;} /* Comfortaa subset, SIL OFL 1.1 */
  :root{--bg:#f1f4f9;--ink:#17202e;--muted:#5f6b7d;--accent:#3355d1;--sd:#c5ccd8;--sl:#ffffff;--radius:18px;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif;font-size:15.5px;-webkit-font-smoothing:antialiased;}
  a:focus-visible,button:focus-visible,input:focus-visible,textarea:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
  .app{display:grid;grid-template-columns:340px minmax(0,1fr);gap:26px;max-width:1280px;margin:0 auto;padding:30px 24px 60px;}
  .card{background:var(--bg);border-radius:var(--radius);box-shadow:8px 8px 18px var(--sd),-8px -8px 18px var(--sl);padding:20px 22px;}
  .side{position:sticky;top:28px;align-self:start;max-height:calc(100vh - 56px);overflow-y:auto;scrollbar-width:none;-ms-overflow-style:none;}
  .side::-webkit-scrollbar{display:none;}
  .brand{padding:0 8px;}
  .brand .logo{font-family:"McTa Wordmark","Baloo 2","Fredoka","Arial Rounded MT Bold","Chalkboard SE","Comic Sans MS",cursive;font-weight:900;letter-spacing:1px;font-size:25px;}
  .wordmark span{display:inline-block;cursor:pointer;user-select:none;transition:transform .25s ease;-webkit-text-stroke:1.5px #fff;paint-order:stroke fill;text-shadow:1.8px 0 0 #fff,-1.8px 0 0 #fff,0 1.8px 0 #fff,0 -1.8px 0 #fff,1.3px 1.3px 0 #fff,-1.3px 1.3px 0 #fff,1.3px -1.3px 0 #fff,-1.3px -1.3px 0 #fff,0 4px 7px rgba(96,108,130,.2);}
  .wordmark span:nth-child(1){transform:rotate(-6deg) translateY(-1px);}
  .wordmark span:nth-child(2){transform:rotate(3deg) translateY(1px);}
  .wordmark span:nth-child(3){transform:rotate(-3deg);}
  .wordmark span:nth-child(4){transform:rotate(5deg) translateY(1px);}
  .w-m,.w-t{color:#e0553d}.w-c{color:#3b57d1}.w-a{color:#17a06b}
  .foot-anim{display:flex;gap:3px;margin:0 0 4px;font-family:"McTa Wordmark","Baloo 2","Fredoka","Arial Rounded MT Bold","Chalkboard SE","Comic Sans MS",cursive;font-size:15.75px;font-weight:900;letter-spacing:1px;user-select:none;}
  .foot-anim span{display:inline-block;-webkit-text-stroke:1.3px #fff;paint-order:stroke fill;animation:hop 1.6s ease-in-out infinite,glow 1.6s ease-in-out infinite;}
  .foot-anim .w-m,.foot-anim .w-t{--glow:224,85,61}
  .foot-anim .w-c{--glow:59,87,209}
  .foot-anim .w-a{--glow:23,160,107}
  .foot-anim span:nth-child(2){animation-delay:.12s}
  .foot-anim span:nth-child(3){animation-delay:.24s}
  .foot-anim span:nth-child(4){animation-delay:.36s}
  @keyframes hop{0%,100%{transform:translateY(0) scale(1)}32%{transform:translateY(-6px) scale(1.14)}52%{transform:translateY(0) scale(1)}}
  @keyframes glow{0%,100%{text-shadow:0 0 0 rgba(var(--glow),0)}32%{text-shadow:0 0 12px rgba(var(--glow),.6),0 0 4px rgba(var(--glow),.45)}}
  .cn,.service{display:block;padding:6px 7px;margin-left:-7px;border-radius:10px;color:#2c3648;font-size:12.5px;line-height:1.7;letter-spacing:.3px;font-weight:700;text-decoration:none;transition:color .12s ease,box-shadow .12s ease;}
  .cn{margin-top:12px;}
  .service{margin-top:2px;margin-bottom:18px;}
  .cn:hover,.service:hover{color:var(--accent);box-shadow:4px 4px 9px var(--sd),-4px -4px 9px var(--sl);}
  .cn:active,.service:active{box-shadow:inset 3px 3px 6px var(--sd),inset -3px -3px 6px var(--sl);}
  button.lang-switch, .side button.lang-switch {
    display: inline-flex; align-items: center; gap: 6px;
    margin: 14px 8px 0; padding: 6px 13px; height: 26px; box-sizing: border-box;
    border: 0; border-radius: 999px;
    background: var(--bg); color: var(--accent);
    font: inherit; font-size: 11.5px; font-weight: 700; line-height: 1;
    cursor: pointer; width: auto; text-align: center;
    box-shadow: 2px 2px 5px var(--sd), -2px -2px 5px var(--sl);
  }
  button.lang-switch:hover { color: var(--accent); }
  button.lang-switch:active {
    box-shadow: inset 3px 3px 6px var(--sd), inset -3px -3px 6px var(--sl);
  }
  .lang-globe { font-size: 13px; line-height: 1; }
  .lang-caret { font-size: 8px; line-height: 1; opacity: .75; }
  .lang-wrap { position: relative; display: inline-flex; }
  .lang-menu {
    position: absolute; top: calc(100% + 6px); left: 0; width: 100%; min-width: 0;
    flex-direction: column; gap: 0; padding: 0; display: none; z-index: 210;
    background: var(--bg); border-radius: 999px; overflow: hidden;
    box-shadow: 4px 4px 12px var(--sd), -4px -4px 12px var(--sl);
  }
  .lang-menu.open { display: flex; }
  .lang-wrap .lang-menu-item {
    display: flex; align-items: center; justify-content: center;
    border: 0; background: transparent; color: var(--accent);
    box-shadow: none; width: 100%; height: 26px; box-sizing: border-box; margin: 0;
    font: inherit; font-size: 11.5px; font-weight: 700; line-height: 1;
    padding: 6px 13px; border-radius: 999px; cursor: pointer;
    text-align: center; white-space: nowrap;
  }
  .lang-wrap .lang-menu-item:hover { background: rgba(120,134,156,.14); box-shadow: none; }
  .lang-wrap .lang-menu-item:active { box-shadow: none; }
  .meta{font-size:13px;color:var(--muted);margin-bottom:6px}
  .root{display:block;word-break:break-all;border-radius:10px;padding:8px 10px;font-size:13px;color:#2f3a4a;box-shadow:inset 3px 3px 6px var(--sd),inset -3px -3px 6px var(--sl);margin-bottom:14px;}
  /* 侧栏信息行：标签后直接空格跟内容（运行目录 + 路径、运行账户 + 用户名） */
  .side-info{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 6px;margin:0 0 6px;}
  .side-info .meta{margin:0;white-space:nowrap;}
  .side-info .root{display:inline;word-break:break-all;padding:0;box-shadow:none;margin:0;font-family:inherit;line-height:1.7;}
  .side-info .account{font-size:13px;color:#2f3a4a;font-weight:600;word-break:break-all;}
  .side .path-row{margin:14px 0 12px;}
  button{font:inherit;border:0;cursor:pointer;border-radius:12px;background:var(--bg);color:#2c3648;padding:9px 14px;box-shadow:4px 4px 9px var(--sd),-4px -4px 9px var(--sl);transition:transform .12s ease,color .12s ease;}
  button:hover{color:var(--accent)}
  button:active{box-shadow:inset 4px 4px 9px var(--sd),inset -4px -4px 9px var(--sl)}
  button:disabled{opacity:.55;cursor:default}
  .side button{width:100%;margin-bottom:10px;text-align:left;}
  .hint{font-size:13px;color:var(--muted);line-height:1.7;margin-top:10px;}

  .head{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px;}
  .head .head-btns{margin-left:auto;display:flex;gap:8px;}
  .head .new-btn{padding:7px 13px;font-size:13px;margin-left:0;}
  .crumbs{display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:14.5px;}
  .crumbs a{color:var(--accent);cursor:pointer;text-decoration:none;padding:4px 8px;margin:-4px -2px;border-radius:9px;transition:color .12s ease,box-shadow .12s ease;}
  .crumbs a:hover{box-shadow:4px 4px 9px var(--sd),-4px -4px 9px var(--sl);}
  .crumbs a:active{box-shadow:inset 3px 3px 6px var(--sd),inset -3px -3px 6px var(--sl);}
  .crumbs span{color:var(--muted);}
  h1{font-size:20px;margin:0 0 4px;}
  .path-row{display:flex;flex-direction:row;align-items:center;gap:8px;margin:0 0 14px;}
  .path-note{display:block;flex:1 1 auto;width:auto;min-width:0;box-sizing:border-box;color:var(--muted);font:inherit;font-size:13.5px;margin:0;padding:6px 9px;border:0;border-radius:9px;background:transparent;box-shadow:inset 2px 2px 5px var(--sd),inset -2px -2px 5px var(--sl);}
  .path-note:focus{outline:none;color:var(--accent);}
  .side .path-row .path-go{width:auto;flex:0 0 auto;align-self:auto;margin:0;padding:6px 10px;font-size:13px;border-radius:9px;color:var(--accent);white-space:nowrap;}
  table{width:100%;border-collapse:collapse;}
  th{font-size:13px;color:var(--muted);text-align:left;font-weight:600;padding:8px 10px;}
  td{padding:9px 10px;border-top:1px solid rgba(120,132,154,.16);font-size:14.5px;overflow-wrap:anywhere;}
  /* 其他文件：多列网格，默认只显示名称 + 类型标签，悬浮显示大小/修改时间 */
  .file-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;}
  .file-grid .entry{display:flex;align-items:center;gap:8px;min-width:0;padding:10px 12px;border-radius:11px;box-shadow:inset 2px 2px 5px var(--sd),inset -2px -2px 5px var(--sl);cursor:pointer;-webkit-touch-callout:none;user-select:none;position:relative;transition:box-shadow .18s ease;}
  .file-grid .entry:hover{box-shadow:3px 3px 9px var(--sd),-3px -3px 9px var(--sl);}
  .file-grid .entry .name{min-width:0;flex:1 1 auto;}
  .file-grid .entry .name .label{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px;}
  .file-grid .entry .tag{flex:0 0 auto;}
  .file-grid .entry .chip-meta{position:absolute;left:10px;top:calc(100% - 4px);z-index:6;display:none;padding:5px 9px;border-radius:8px;background:var(--bg);box-shadow:4px 4px 11px var(--sd),-4px -4px 11px var(--sl);font-size:12px;color:var(--muted);white-space:nowrap;pointer-events:none;}
  .file-grid .entry:hover .chip-meta{display:block;}
  .name{display:flex;align-items:center;gap:8px;}
  .tag{font-size:11.5px;color:var(--muted);border-radius:7px;padding:1px 7px;box-shadow:inset 2px 2px 4px var(--sd),inset -2px -2px 4px var(--sl);}
  .muted{color:var(--muted);}
  .empty{padding:24px 4px;color:var(--muted);text-align:center;}
  [data-base-id="quickView"] .mol-win{max-height:calc(100vh - 32px);display:flex;flex-direction:column;}
  [data-base-id="molView"]:not(.maxed) .mol-win,[data-base-id="quickView"].preview:not(.maxed) .mol-win{height:calc(100vh - 32px);display:flex;flex-direction:column;}
  [data-base-id="molView"]:not(.maxed) .mol-canvas{flex:1;height:auto;min-height:0;}
  [data-base-id="quickView"].preview:not(.maxed) #quickBody{flex:1;min-height:0;}
  [data-base-id="quickView"].preview:not(.maxed) #quickBody textarea{height:auto;flex:1;min-height:0;resize:none;}
  [data-base-id="quickView"].preview:not(.maxed) .md-view,[data-base-id="quickView"].preview:not(.maxed) .json-view{height:auto;flex:1;min-height:0;overflow:auto;}
  [data-base-id="quickView"].preview:not(.maxed) .pdf-frame{height:auto;flex:1;min-height:0;}
  [data-base-id="quickView"].preview:not(.maxed) .zoom-box{height:auto;}
  #quickBody{min-height:80px;overflow:auto;display:flex;flex-direction:column;}
  .zoom-box{position:relative;display:flex;align-items:center;justify-content:center;flex:1;min-height:0;height:min(62vh,480px);overflow:hidden;border-radius:12px;background:#fff;cursor:grab;touch-action:none;box-shadow:inset 4px 4px 9px var(--sd),inset -4px -4px 9px var(--sl);}
  .zoom-box.dragging{cursor:grabbing;}
  .zoom-box img{max-width:100%;max-height:100%;border-radius:12px;pointer-events:none;user-select:none;transform-origin:center center;will-change:transform;}
  #quickBody textarea{width:100%;height:min(58vh,430px);resize:vertical;border:0;border-radius:12px;background:#f3f6fb;color:#2f3a4a;font-family:ui-monospace,Consolas,"Courier New",monospace;font-size:12.5px;line-height:1.6;padding:12px 14px;box-shadow:inset 5px 5px 10px var(--sd),inset -5px -5px 10px var(--sl);outline:none;}
  #quickBody input.rename-input{width:100%;border:0;border-radius:12px;background:#f3f6fb;color:#2f3a4a;font:inherit;font-size:14.5px;padding:12px 14px;box-shadow:inset 5px 5px 10px var(--sd),inset -5px -5px 10px var(--sl);outline:none;}
  .pdf-frame{width:100%;height:min(58vh,430px);border:0;border-radius:12px;background:#fff;box-shadow:inset 5px 5px 10px var(--sd),inset -5px -5px 10px var(--sl);}
  .md-view{padding:14px 18px;line-height:1.75;background:#f3f6fb;border-radius:12px;box-shadow:inset 5px 5px 10px var(--sd),inset -5px -5px 10px var(--sl);min-height:100px;}
  .md-view h1,.md-view h2,.md-view h3,.md-view h4,.md-view h5,.md-view h6{margin:.7em 0 .35em;line-height:1.35;}
  .md-view p{margin:.45em 0;}
  .md-view ul,.md-view ol{margin:.4em 0 .4em 1.4em;padding:0;}
  .md-view blockquote{margin:.5em 0;padding:4px 12px;border-left:3px solid var(--accent);color:var(--muted);}
  .md-view code{font-family:ui-monospace,Consolas,"Courier New",monospace;background:rgba(120,132,154,.16);padding:1px 4px;border-radius:5px;font-size:12.5px;}
  .md-view pre{overflow:auto;padding:10px 12px;border-radius:10px;background:#10151d;color:#d7deea;}
  .md-view pre code{background:transparent;padding:0;color:inherit;}
  .md-view a{color:var(--accent);}
  .md-view table{border-collapse:collapse;font-size:13px;margin:.5em 0;}
  .md-view th,.md-view td{border:1px solid rgba(120,132,154,.3);padding:4px 8px;text-align:left;}
  .data-table{border-collapse:collapse;width:100%;font-size:13px;background:#fff;border-radius:10px;overflow:hidden;}
  .data-table th,.data-table td{border:1px solid rgba(120,132,154,.22);padding:6px 9px;text-align:left;white-space:nowrap;}
  .data-table th{background:#eaeff7;color:#2f3a4a;font-weight:600;position:sticky;top:0;}
  .data-note{font-size:12.5px;color:var(--muted);padding:6px 2px;}
  .json-view{font-family:ui-monospace,Consolas,"Courier New",monospace;font-size:13px;line-height:1.65;padding:12px 14px;border-radius:12px;background:#f3f6fb;box-shadow:inset 5px 5px 10px var(--sd),inset -5px -5px 10px var(--sl);white-space:pre-wrap;overflow-wrap:anywhere;}
  .json-view details{margin-left:16px;}
  .json-view summary{cursor:pointer;color:var(--accent);}
  .json-key{color:#3355d1}.json-str{color:#17805a}.json-num{color:#b1522a}.json-bool{color:#8a45b5}.json-null{color:#7a8798}
  .quick-media{display:block;max-width:100%;max-height:min(68vh,720px);margin:auto;border-radius:12px;background:#10151d;}
  .audio-view{display:flex;align-items:center;justify-content:center;gap:14px;flex:1;min-height:180px;color:#2f3a4a;font-size:15px;}
  .audio-view .audio-glyph{width:64px;height:64px;border-radius:18px;display:flex;align-items:center;justify-content:center;background:#f3f6fb;box-shadow:5px 5px 11px var(--sd),-5px -5px 11px var(--sl);}
  .audio-view .audio-glyph svg{width:32px;height:32px;fill:var(--accent);}
  .quick-tools{justify-content:center;flex:none;margin-top:8px;}
  .file-menu{position:fixed;left:0;top:0;z-index:14;min-width:158px;padding:8px;border-radius:14px;background:var(--bg);box-shadow:8px 8px 18px var(--sd),-8px -8px 18px var(--sl);display:flex;flex-direction:column;gap:6px;}
  .file-menu button{display:block;width:100%;text-align:left;padding:11px 14px;border:0;border-radius:9px;background:transparent;font-size:13.5px;color:#2c3648;cursor:pointer;}
  .file-menu button:hover{box-shadow:inset 2px 2px 5px var(--sd),inset -2px -2px 5px var(--sl);}
  .gallery{display:grid;gap:16px;margin:6px 0 20px;}
  .gallery.g1{grid-template-columns:80%;justify-content:center;}
  .gallery.g1 .shot img{height:auto;max-height:70vh;}
  .gallery.g2{grid-template-columns:repeat(2,minmax(0,1fr));}
  .gallery.g3{grid-template-columns:repeat(3,minmax(0,1fr));}
  .shot{border-radius:14px;padding:10px;background:var(--bg);box-shadow:6px 6px 14px var(--sd),-6px -6px 14px var(--sl);cursor:pointer;transition:transform .12s ease;-webkit-touch-callout:none;user-select:none;}
  .shot:hover{transform:translateY(-2px)}
  .shot img{display:block;width:100%;height:300px;object-fit:contain;border-radius:10px;background:#fff;}
  .shot span{display:block;margin-top:8px;font-size:13.5px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .shot:hover span{color:var(--accent)}
  .term-wrap{margin-top:18px;}
  .term-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;}
  .term-wrap:not(.floating) .term-head{cursor:pointer;}
  .term-title{display:flex;align-items:center;gap:8px;min-width:0;}
  .term-head .t{font-size:13px;font-weight:600;color:#2c3648;}
  .term-tools{display:none;margin-left:auto;gap:3px;flex:none;}
  .term-wrap.floating .term-tools{display:flex;}
  .term-tools button{width:24px;height:24px;padding:0;border-radius:7px;font-size:13px;line-height:1;display:inline-flex;align-items:center;justify-content:center;box-shadow:2px 2px 5px var(--sd),-2px -2px 5px var(--sl);}
  .term-tools button:hover{color:var(--accent);}
  .term-tools button:active{box-shadow:inset 2px 2px 4px var(--sd),inset -2px -2px 4px var(--sl);}
  .term-tools .win-glyph{display:inline-flex;align-items:center;justify-content:center;line-height:1;}
  .win-glyph svg{display:block;width:15px;height:15px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;}
  .term-wrap.floating{position:fixed;z-index:8;display:flex;flex-direction:column;margin:0;padding:10px 12px 12px;border-radius:18px;background:var(--bg);box-shadow:0 18px 44px rgba(28,42,64,.26),0 2px 8px rgba(28,42,64,.14),8px 8px 18px var(--sd),-8px -8px 18px var(--sl);max-width:calc(100vw - 12px);max-height:calc(100vh - 12px);}
  .term-wrap.floating .term-head{cursor:move;touch-action:none;margin-bottom:8px;}
  .term-wrap.floating .term-box{flex:1 1 auto;height:auto;min-height:140px;}
  .term-wrap.floating .term-note{display:none;}
  .term-wrap.dragging{user-select:none;}
  .term-wrap.floating .resize-handle{position:absolute;z-index:2;display:block;}
  .term-wrap.floating .rh-t{top:-3px;left:10px;right:10px;height:6px;cursor:ns-resize;}
  .term-wrap.floating .rh-b{bottom:-3px;left:10px;right:10px;height:6px;cursor:ns-resize;}
  .term-wrap.floating .rh-l{left:-3px;top:10px;bottom:10px;width:6px;cursor:ew-resize;}
  .term-wrap.floating .rh-r{right:-3px;top:10px;bottom:10px;width:6px;cursor:ew-resize;}
  .term-wrap.floating .rh-tl{top:-3px;left:-3px;width:12px;height:12px;cursor:nwse-resize;}
  .term-wrap.floating .rh-tr{top:-3px;right:-3px;width:12px;height:12px;cursor:nesw-resize;}
  .term-wrap.floating .rh-bl{bottom:-3px;left:-3px;width:12px;height:12px;cursor:nesw-resize;}
  .term-wrap.floating .rh-br{bottom:-3px;right:-3px;width:12px;height:12px;cursor:nwse-resize;}
  .term-note{color:var(--muted);font-size:12.5px;line-height:1.6;margin:8px 0 0;}
  .side-foot{display:flex;gap:8px;align-items:center;margin:16px 2px 0;font-size:12.5px;color:var(--muted);}
  .side-foot a{color:var(--accent);text-decoration:none;}
  .side-foot a:hover{text-decoration:underline}
  .license-link{cursor:pointer;}
  .license-link:hover{text-decoration:underline;}
  .license-overlay{position:fixed;inset:0;z-index:9700;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(23,32,46,.03);-webkit-backdrop-filter:blur(2px);backdrop-filter:blur(2px);}
  .license-text{margin:0;position:relative;max-width:min(680px,94vw);max-height:80vh;overflow:auto;scrollbar-width:none;-ms-overflow-style:none;white-space:pre-wrap;overflow-wrap:anywhere;padding:22px 28px;background:transparent;border:0;box-shadow:none;color:#fff;font-family:ui-monospace,Consolas,"Courier New",monospace;font-size:13px;line-height:1.7;text-shadow:0 0 2px rgba(8,14,26,1),0 0 10px rgba(8,14,26,.9),0 0 22px rgba(8,14,26,.6);}
  .license-text::-webkit-scrollbar{display:none;}
  .license-line{display:block;min-height:1.7em;visibility:hidden;}
  .license-line.shown{visibility:visible;animation:lic-line-in .32s ease-out both;}
  @keyframes lic-line-in{from{opacity:0}to{opacity:1}}
  .foot{margin:18px 2px 4px;color:var(--muted);font-size:12.5px;line-height:1.7;}
  .foot-title{font-size:12.5px;font-weight:700;color:#2c3648;margin:0 0 6px;}
  .foot p{margin:0;}
  .foot a{color:var(--accent);text-decoration:none;}
  .foot a:hover{text-decoration:underline}
  .term-box{position:relative;border-radius:14px;padding:10px;background:#10151d;box-shadow:inset 5px 5px 12px #0a0e14,inset -3px -3px 8px #1a2230;height:260px;overflow:hidden;}
  .term-box .xterm{height:100%;position:relative;z-index:1;}
  .term-rain{position:absolute;inset:0;z-index:2;pointer-events:none;opacity:.28;transition:opacity .35s ease;border-radius:14px;}
  .term-hint{color:#9aa7bd;font-size:13.5px;line-height:1.8;padding:8px 4px;position:relative;z-index:1;}
  .mol-mask{position:fixed;inset:0;background:transparent;display:flex;align-items:center;justify-content:center;padding:16px;z-index:12;opacity:0;visibility:hidden;transition:opacity .25s ease,visibility .25s ease;}
  .mol-mask:not(.hidden){opacity:1;visibility:visible;pointer-events:none;}
  .mol-mask.maxed{padding:8px;pointer-events:auto;}
  .mol-win{position:relative;width:min(760px,100%);background:var(--bg);border-radius:18px;padding:10px 12px 12px;box-shadow:0 18px 44px rgba(28,42,64,.26),0 2px 8px rgba(28,42,64,.14),8px 8px 18px var(--sd),-8px -8px 18px var(--sl);transform:scale(.96) translateY(8px);transition:transform .28s cubic-bezier(.34,1.56,.64,1),box-shadow .3s ease;pointer-events:auto;}
  .mol-mask:not(.hidden) .mol-win{transform:none;}
  /* 自由浮动：被拖动/缩放后切换到 fixed 定位 */
  .mol-mask:not(.hidden) .mol-win.free{position:fixed;transform:none;transition:none;margin:0;}
  .mol-mask.maxed .mol-win.free{position:relative;left:auto!important;top:auto!important;width:100%!important;height:100%!important;max-width:none!important;max-height:none!important;}
  /* 调整大小后窗口为 fixed + inline left/top；最大化须覆盖这些内联几何，退出 maxed 后自动恢复 */
  /* 四边/四角 resize 热区：与终端一致，透明无边框，只在边缘显示缩放光标 */
  .mol-rh{position:absolute;z-index:3;display:none;width:12px;height:12px;background:transparent;}
  .mol-mask:not(.hidden) .mol-rh{display:block;}
  .mol-rh::before{content:none;}
  .mol-rh-t{top:-3px;left:10px;right:10px;width:auto;height:6px;cursor:ns-resize;}
  .mol-rh-b{bottom:-3px;left:10px;right:10px;width:auto;height:6px;cursor:ns-resize;}
  .mol-rh-l{left:-3px;top:10px;bottom:10px;width:6px;height:auto;cursor:ew-resize;}
  .mol-rh-r{right:-3px;top:10px;bottom:10px;width:6px;height:auto;cursor:ew-resize;}
  .mol-rh-tl{top:-3px;left:-3px;cursor:nwse-resize;}
  .mol-rh-tr{top:-3px;right:-3px;cursor:nesw-resize;}
  .mol-rh-bl{bottom:-3px;left:-3px;cursor:nesw-resize;}
  .mol-rh-br{bottom:-3px;right:-3px;cursor:nwse-resize;}
  .mol-mask:not(.hidden) .mol-head{cursor:move;user-select:none;}
  .mol-mask.maxed .mol-head{cursor:default;}
  .mol-head h2,.mol-head button{user-select:none;}
  /* 还原按钮：与终端还原按钮风格一致 */
  .mol-head{display:flex;align-items:center;gap:8px;margin:0 0 8px;}
  .mol-head h2{font-size:13px;font-weight:600;color:#2c3648;margin:0;flex:1;min-width:0;overflow-wrap:anywhere;}
  .mol-mask.maxed{padding:8px;}
  .mol-mask.maxed .mol-win{width:100%;max-width:none;height:100%;max-height:none;border-radius:18px;display:flex;flex-direction:column;}
  .mol-mask.maxed .mol-canvas{flex:1;height:auto;min-height:0;border-radius:10px;}
  .mol-mask.maxed .mol-win>.mol-player{flex:none;}
  .mol-mask.maxed #quickBody{flex:1;min-height:0;}
  .mol-mask.maxed #quickBody textarea{height:auto;flex:1;min-height:0;resize:none;}
  .mol-mask.maxed .md-view,.mol-mask.maxed .json-view{height:auto;flex:1;min-height:0;overflow:auto;}
  .mol-mask.maxed .pdf-frame{height:auto;flex:1;min-height:0;}
  .mol-mask.maxed .quick-media{max-height:calc(100vh - 120px);}
  .mol-mask.maxed .zoom-box{height:auto;}
  [data-base-id="quickView"].maxed .mol-win{max-height:none;}
  [data-base-id="quickView"].image-mode .zoom-box{background:#fff;}
  .mol-canvas{position:relative;width:100%;height:min(62vh,460px);border-radius:14px;overflow:hidden;background:#fff;box-shadow:inset 5px 5px 11px var(--sd),inset -5px -5px 11px var(--sl);}
  /* 左下角坐标轴指示器：固定长度，只跟随结构旋转，不随平移/缩放变化 */
  .mol-axis-gizmo{position:absolute;left:12px;bottom:12px;width:120px;height:120px;z-index:5;background:transparent;box-shadow:none;cursor:grab;touch-action:none;}
  .mol-axis-gizmo.dragging{cursor:grabbing;}
  .mol-note{color:var(--muted);font-size:12.5px;line-height:1.7;margin:9px 2px 0;}
  .mol-save{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;border-radius:18px;background:rgba(231,237,246,.78);z-index:3;}
  .mol-save-win{width:min(460px,92%);background:var(--bg);border-radius:14px;padding:14px 16px 16px;box-shadow:7px 7px 16px var(--sd),-7px -7px 16px var(--sl);}
  .mol-save-win>p{margin:0 0 12px;font-size:14px;font-weight:600;color:#2f3a4a;}
  .mol-save-options{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:0 0 12px;}
  .mol-save-options label,.mol-save-name-label{display:block;font-size:12.5px;color:var(--muted);}
  .mol-save-options select{display:block;width:100%;height:32px;margin-top:5px;padding:0 8px;font:inherit;font-size:13px;border:0;border-radius:10px;background:var(--bg);color:inherit;box-shadow:3px 3px 7px var(--sd),-3px -3px 7px var(--sl);}
  .mol-save-name-label{margin:0 0 5px;}
  .mol-save-win input{width:100%;border:0;border-radius:10px;background:#f3f6fb;color:#2f3a4a;font:inherit;font-size:13.5px;padding:9px 12px;box-shadow:inset 4px 4px 8px var(--sd),inset -4px -4px 8px var(--sl);outline:none;}
  .mol-save-ops{display:flex;justify-content:flex-end;gap:8px;margin-top:12px;}
  .mol-save-ops button{height:32px;padding:0 16px;font-size:13.5px;}
  .mol-head button{height:30px;padding:0 12px;font-size:13px;border-radius:12px;}
  /* 弹窗顶部按钮与终端浮窗 .term-tools button 同款 */
  .mol-head .win-icon{width:24px;min-width:24px;height:24px;padding:0;display:inline-flex;align-items:center;justify-content:center;border-radius:7px;background:var(--bg);box-shadow:2px 2px 5px var(--sd),-2px -2px 5px var(--sl);color:#2c3648;font-size:13px;line-height:1;}
  .mol-head .win-icon:hover{color:var(--accent);}
  .mol-head .win-icon:active{box-shadow:inset 2px 2px 5px var(--sd),inset -2px -2px 5px var(--sl);}
  .mol-head .win-glyph{display:inline-flex;align-items:center;justify-content:center;line-height:1;}
  .mol-tools button.tool-icon{width:30px;min-width:30px;padding:0;display:inline-flex;align-items:center;justify-content:center;}
  .mol-tools .tool-icon svg{display:block;width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;}
  .mol-tools,.mol-player{display:flex;align-items:center;gap:8px;margin:10px 2px 0;flex-wrap:wrap;}
  .mol-tools>.mol-dd,.mol-tools>.mol-density-group,.mol-tools>.mol-player{display:flex;align-items:center;height:30px;align-self:center;margin:0;gap:6px;}
  .mol-tools>.mol-player button,.mol-tools>.mol-player .mol-count{height:30px;line-height:30px;align-self:center;}
  .mol-tools>.mol-player input[type=range]{height:16px;align-self:center;margin-top:0;margin-bottom:0;}
  .mol-tools>.mol-player .mol-dd{height:30px;align-self:center;margin:0;}
  .mol-tools button,.mol-player button{height:30px;padding:0 12px;font-size:13px;border-radius:12px;}
  .mol-tools select,.mol-player select{height:30px;padding:0 8px;font-size:13px;border-radius:12px;background:var(--bg);color:inherit;border:0;box-shadow:3px 3px 7px var(--sd),-3px -3px 7px var(--sl);}
  .mol-tools .mol-tag{font-size:12.5px;color:var(--muted);line-height:30px;display:inline-flex;align-items:center;height:30px;}
  .mol-tools .mol-sep{width:1px;height:18px;background:rgba(120,134,156,.3);margin:0 2px;flex-shrink:0;}
  .mol-player input[type=range]{flex:1;min-width:120px;max-width:280px;}
  .mol-player .mol-count{font-size:12.5px;color:var(--muted);text-align:left;line-height:30px;font-variant-numeric:tabular-nums;flex-shrink:0;margin-right:-2px;}
  .mol-density-group{display:flex;align-items:center;gap:6px;height:30px;}
  .mol-density-kind{height:30px;padding:0 8px;font-size:13px;border-radius:12px;background:var(--bg);color:inherit;border:0;box-shadow:3px 3px 7px var(--sd),-3px -3px 7px var(--sl);margin-right:4px;}
  .mol-density-field{position:relative;display:inline-flex;align-items:center;gap:4px;height:30px;}
  .mol-density-field .mol-tag{font-size:12.5px;color:var(--muted);line-height:30px;}
  .mol-density-field input[type=number]{width:76px;height:26px;padding:0 6px;border:0;border-radius:9px;background:#f3f6fb;color:#2f3a4a;font:inherit;font-size:12.5px;box-shadow:inset 2px 2px 5px var(--sd),inset -2px -2px 5px var(--sl);outline:none;}
  .mol-density-field .mol-density-pop{width:22px;min-width:22px;height:26px;padding:0;font-size:10px;border-radius:8px;border:0;background:var(--bg);color:var(--muted);box-shadow:2px 2px 5px var(--sd),-2px -2px 5px var(--sl);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;line-height:1;}
  .mol-density-field .mol-density-pop:hover{color:#2f3a4a;}
  .mol-density-field .mol-density-pop.active{color:#2563eb;background:#dbeafe;}
  .mol-density-panel{position:absolute;bottom:calc(100% + 8px);left:50%;transform:translateX(-50%);background:var(--bg);box-shadow:6px 6px 14px var(--sd),-6px -6px 14px var(--sl);border-radius:12px;padding:10px 12px 8px;display:flex;flex-direction:column;align-items:center;gap:6px;z-index:13;min-width:90px;opacity:0;visibility:hidden;pointer-events:none;transition:opacity .15s;}
  .mol-density-panel.show{opacity:1;visibility:visible;pointer-events:auto;}
  .mol-density-track{width:80px;height:120px;position:relative;}
  .mol-density-track input[type=range]{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%) rotate(-90deg);transform-origin:center center;width:120px;height:20px;margin:0;cursor:pointer;}
  .mol-density-val{font-size:12px;font-weight:600;color:#2f3a4a;font-variant-numeric:tabular-nums;}
  .mol-pick-panel{position:absolute;z-index:20;width:248px;padding:10px 12px;border-radius:12px;background:var(--bg);box-shadow:6px 6px 14px var(--sd),-6px -6px 14px var(--sl);font-size:13px;display:flex;flex-direction:column;gap:8px;}
  .mol-pick-panel.hidden{display:none;}
  .mol-pick-title{font-weight:600;color:#2f3a4a;font-size:13px;}
  .mol-pick-row{position:relative;display:flex;align-items:center;justify-content:flex-start;gap:8px;color:var(--muted);min-height:26px;}
  .mol-pick-row > span{margin-right:auto;}
  .mol-pick-row.hidden{display:none;}
  .mol-pick-panel input[type=color]{width:40px;height:24px;padding:0;border:0;background:transparent;box-shadow:none;cursor:pointer;}
  .mol-pick-num-btn{height:24px;width:20px;min-width:20px;padding:0;font-size:10px;line-height:1;border:0;border-radius:7px;background:var(--bg);color:#2f3a4a;box-shadow:2px 2px 5px var(--sd),-2px -2px 5px var(--sl);cursor:pointer;}
  .mol-pick-num-btn.active{box-shadow:inset 2px 2px 5px var(--sd),inset -2px -2px 5px var(--sl);color:#2563eb;}
  .mol-pick-panel input[type=number]{width:58px;height:24px;padding:0 5px;border:0;border-radius:8px;background:#f3f6fb;color:#2f3a4a;font:inherit;font-size:12px;font-variant-numeric:tabular-nums;box-shadow:inset 2px 2px 5px var(--sd),inset -2px -2px 5px var(--sl);outline:none;}
  .mol-pick-pop{position:absolute;right:-14px;bottom:calc(100% + 6px);width:48px;height:124px;padding:6px 0;border-radius:10px;background:var(--bg);box-shadow:5px 5px 12px var(--sd),-5px -5px 12px var(--sl);opacity:0;visibility:hidden;pointer-events:none;transition:opacity .12s;z-index:22;}
  .mol-pick-pop.show{opacity:1;visibility:visible;pointer-events:auto;}
  .mol-pick-pop input[type=range]{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%) rotate(-90deg);width:106px;height:16px;margin:0;cursor:pointer;}
  .mol-pick-ops{display:flex;justify-content:flex-end;gap:6px;}
  .mol-pick-ops button{height:24px;padding:0 9px;font-size:12px;border-radius:8px;}
  .mol-pick-tabs{display:flex;gap:4px;padding:2px 0 5px;border-bottom:1px solid rgba(120,140,170,.2);}
  .mol-pick-tabs button{flex:1;height:23px;padding:0 3px;font-size:11px;border:0;border-radius:7px;background:transparent;color:var(--muted);cursor:pointer;white-space:nowrap;}
  .mol-pick-tabs button.active{background:#eaf1ff;color:#2563eb;font-weight:600;}
  .mol-pick-group{display:flex;flex-direction:column;gap:8px;}
  .mol-pick-group.hidden{display:none;}
  .mol-pick-panel input[type=checkbox]{width:18px;height:18px;accent-color:#2563eb;cursor:pointer;}
  .mol-dd{position:relative;display:inline-block;}
  .mol-dd-btn{height:30px;padding:0 10px;font-size:13px;border-radius:12px;background:var(--bg);color:inherit;border:0;box-shadow:3px 3px 7px var(--sd),-3px -3px 7px var(--sl);cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;gap:4px;}
  .mol-dd.open .mol-dd-btn{box-shadow:inset 2px 2px 5px var(--sd),inset -2px -2px 5px var(--sl);}
  .mol-dd-menu{position:absolute;right:0;bottom:calc(100% + 6px);margin:0;padding:4px 0;border-radius:12px;background:var(--bg);box-shadow:6px 6px 14px var(--sd),-6px -6px 14px var(--sl);list-style:none;min-width:96px;z-index:13;opacity:0;visibility:hidden;pointer-events:none;transition:opacity .12s;}
  .mol-dd.open .mol-dd-menu{opacity:1;visibility:visible;pointer-events:auto;}
  .mol-dd-menu li{padding:6px 14px;font-size:13px;color:#425066;cursor:pointer;font-variant-numeric:tabular-nums;}
  .mol-dd-menu li:hover{background:rgba(37,99,235,.08);color:#1d4ed8;}
  .mol-dd-menu li[aria-selected="true"]{color:#1d4ed8;font-weight:600;}
  .toast{position:fixed;left:50%;bottom:26px;transform:translate(-50%,10px);opacity:0;pointer-events:none;padding:9px 16px;border-radius:12px;background:var(--bg);box-shadow:6px 6px 14px var(--sd),-6px -6px 14px var(--sl);font-size:14px;transition:opacity .2s ease,transform .2s ease,left 0s,top 0s;z-index:9500;max-width:80vw;}
  .toast.show{opacity:1;transform:translate(-50%,0)}
  .toast.anchored{bottom:auto;transform:translate(-50%,calc(-100% - 2px));}
  .toast.anchored.show{opacity:1;transform:translate(-50%,calc(-100% - 10px));}
  .toast.err{color:#c0392b}
  .confirm-mask{position:fixed;inset:0;background:rgba(20,28,42,.45);z-index:10000;display:flex;align-items:center;justify-content:center;}
  .confirm-box{min-width:280px;max-width:92vw;background:var(--bg);border-radius:14px;box-shadow:8px 8px 20px var(--sd),-8px -8px 20px var(--sl);padding:0;overflow:hidden;}
  .confirm-head{padding:14px 20px 8px;font-weight:600;font-size:15px;color:#2f3a4a;}
  .confirm-body{padding:2px 20px 14px;font-size:13.5px;color:#556073;line-height:1.7;}
  .confirm-body b{color:#2f3a4a;}
  .confirm-foot{display:flex;justify-content:flex-end;gap:10px;padding:10px 16px 14px;border-top:1px solid rgba(120,134,156,.15);}
  .confirm-foot button{padding:6px 16px;font-size:13px;border-radius:10px;border:0;cursor:pointer;font-family:inherit;transition:.12s;}
  .confirm-foot .btn-cancel{background:transparent;color:#556073;box-shadow:3px 3px 7px var(--sd),-3px -3px 7px var(--sl);}
  .confirm-foot .btn-cancel:hover{color:#2f3a4a;}
  .confirm-foot .btn-ok{background:#2563eb;color:#fff;box-shadow:3px 3px 7px var(--sd),-3px -3px 7px var(--sl);}
  .confirm-foot .btn-ok:hover{background:#1d4ed8;}
  .confirm-foot .btn-ok.danger{background:#dc2626;}
  .confirm-foot .btn-ok.danger:hover{background:#b91c1c;}
  .hidden{display:none!important;}
  /* 最小化：主体隐藏，只留顶端栏，停靠页面下方从左到右排列 */
  .term-wrap.floating.win-min,.mol-win.win-min{width:auto!important;height:40px!important;min-width:0!important;min-height:40px!important;max-width:calc(100vw - 8px)!important;max-height:40px!important;padding:6px 10px!important;border-radius:12px!important;overflow:visible!important;transition:none!important;transform:none!important;white-space:nowrap;}
  /* 文件浮窗默认 position:relative（居中容器），停靠的 left/top 会变成相对偏移导致窗口消失；最小化时必须 fixed。 */
  .mol-mask:not(.hidden) .mol-win.win-min{position:fixed!important;margin:0!important;z-index:14;}
  .term-wrap.floating.win-min .term-box,.term-wrap.floating.win-min .resize-handle,.term-wrap.floating.win-min .term-note,.mol-win.win-min>*:not(.mol-head){display:none!important;}
  .term-wrap.floating.win-min .term-head,.mol-win.win-min .mol-head{margin:0!important;cursor:default!important;}
  /* 最小化态只保留：最大化 + 还原到侧栏（终端）/ 关闭（文件浮窗）；顶栏文字可点击还原。 */
  .term-wrap.floating.win-min .term-tools button:not([data-term-act="max"]):not([data-term-act="dock"]){display:none!important;}
  .term-wrap.floating.win-min .term-title,.mol-win.win-min .mol-head h2{cursor:pointer!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;}
  .mol-win.win-min .mol-head h2{font-size:0;}
  /* 停靠态只渲染 data-dock-name，即便标题文本被其它逻辑写回完整信息也不会显示大小/日期 */
  .mol-win.win-min .mol-head h2::before{content:attr(data-dock-name);font-size:13px;font-weight:600;color:#2c3648;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;}
  /* 停靠栏只显示名字：终端隐藏状态文字，文件浮窗标题在 JS 里精简为纯文件名 */
  /* 停靠栏显示连接状态 + 运行账户（termState 已含用户名） */
  .term-wrap.floating.win-min .term-title .muted{display:inline!important;font-size:11.5px;opacity:.9;}
  .mol-win.win-min .mol-head .min-btn,.mol-win.win-min .mol-head .restore-btn,.mol-win.win-min .mol-head .win-icon:not(.max-btn):not(.close-icon){display:none!important;}
  .mol-mask.hidden{opacity:0;visibility:hidden;display:flex!important;}
  @media (max-width:600px){.mol-density-field .mol-tag{display:none;}.mol-density-kind{font-size:12px;}}
  @media (max-width:900px){.app{grid-template-columns:1fr;padding:18px 14px 40px}.side{position:static;max-height:none;overflow:visible}.term-box{height:220px}.shot img{height:180px}}
</style>
</head>
<body>
<div class="app">
  <aside class="side card">
    <div class="brand">
      <div class="logo wordmark" role="img" aria-label="McTa"><span class="w-m">M</span><span class="w-c">c</span><span class="w-t">T</span><span class="w-a">a</span></div>
      <span class="lang-wrap" id="langWrap"><button type="button" class="lang-switch" id="langToggle" title="切换语言 / Switch language" aria-label="切换语言 / Switch language" aria-haspopup="true" aria-expanded="false"><span class="lang-globe" aria-hidden="true">◎</span><span class="lang-name">中文</span><span class="lang-caret" aria-hidden="true">▼</span></button><span class="lang-menu" id="langMenu" role="menu"><button type="button" class="lang-menu-item" id="langMenuItem" role="menuitem">English</button></span></span>
    </div>
    <a class="cn" href="https://lkccrr.github.io/mcta/" target="_blank" rel="noopener noreferrer">格塔 · Meta Crystal Toolkit &amp; Analysis</a>
    <a class="service" href="https://lkccrr.github.io/mcta/#server" target="_blank" rel="noopener noreferrer">mt.server</a>

    <div class="side-info"><span class="meta" id="rootLabel">运行目录</span><code class="root" id="rootPath">读取中…</code></div>
    <div class="side-info"><span class="meta">运行账户</span><span class="account" id="authText"></span></div>

    <div class="path-row">
      <input class="path-note" id="pathNote" type="text" spellcheck="false" autocomplete="off" title="输入路径后回车切换目录" aria-label="输入路径后回车切换目录">
      <button class="path-go" id="pathGo" type="button" title="进入" aria-label="进入">进入</button>
    </div>

    <div class="side-foot">
      <a href="https://github.com/lkccrr/mcta" target="_blank" rel="noopener noreferrer">GitHub</a><span>·</span>
      <a href="https://pypi.org/project/mcta/" target="_blank" rel="noopener noreferrer">PyPI</a><span>·</span>
      <a class="license-link" id="sideMit" href="#" role="button" tabindex="0" title="查看许可">MIT</a>
    </div>

    <div class="term-wrap">
      <div class="term-head">
        <span class="term-title">
          <span class="t">终端</span>
          <span class="muted" id="termState" aria-live="polite">连接中…</span>
        </span>
        <span class="term-tools" role="group" aria-label="终端窗口">
          <button type="button" data-term-act="min" title="最小化" aria-label="最小化"><span class="win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12h14"/></svg></span></button>
          <button type="button" data-term-act="restore" title="还原" aria-label="还原"><span class="win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M3 11a9 9 0 1 1 2.6 6.4"/><path d="M3 5v6h6"/></svg></span></button>
          <button type="button" data-term-act="max" title="放大到整个页面" aria-label="放大到整个页面"><span class="max-icon win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M7 17 17 7"/><path d="M9 7h8v8"/></svg></span><span class="restore-icon win-glyph hidden" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M17 7 7 17"/><path d="M15 17H7V9"/></svg></span></button>
          <button type="button" data-term-act="dock" title="还原到侧栏" aria-label="还原到侧栏"><span class="win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/><path d="m14 9-3 3 3 3"/></svg></span></button>
        </span>
      </div>
      <div class="term-box" id="termBox">
        <canvas class="term-rain" id="termRain" aria-hidden="true"></canvas>
        <div class="term-hint" id="termHint">正在连接终端…</div>
      </div>
      <span class="resize-handle rh-tl"></span><span class="resize-handle rh-t"></span><span class="resize-handle rh-tr"></span>
      <span class="resize-handle rh-l"></span><span class="resize-handle rh-r"></span>
      <span class="resize-handle rh-bl"></span><span class="resize-handle rh-b"></span><span class="resize-handle rh-br"></span>
    </div>

  </aside>

  <main>
    <section class="card" id="browser">
      <div class="head"><div class="crumbs" id="crumbs"></div><div class="head-btns"><button id="btnNewDir" class="new-btn">新建目录</button><button id="btnNewText" class="new-btn">新建文本</button></div></div>
      <div class="gallery hidden" id="gallery"></div>
      <div class="meta hidden" id="othersLabel">其他文件</div>
      <div id="fileTable" class="file-grid"></div>
      <div class="empty hidden" id="empty">此目录为空</div>
    </section>

    <footer class="foot">
      <div class="foot-anim" aria-hidden="true"><span class="w-m">M</span><span class="w-c">c</span><span class="w-t">T</span><span class="w-a">a</span></div>
      <p class="foot-title">许可</p>
      <p><a class="license-link" id="footMit" href="#" role="button" tabindex="0" title="查看许可">MIT License</a><span> · 源码与问题反馈：</span>
        <a href="https://github.com/lkccrr/mcta" target="_blank" rel="noopener noreferrer">GitHub</a> ·
        <a href="https://pypi.org/project/mcta/" target="_blank" rel="noopener noreferrer">PyPI</a>
      </p>
    </footer>
  </main>
</div>
<div class="mol-mask hidden" id="molView" data-base-id="molView">
  <div class="mol-win">
    <div class="mol-head">
      <h2 id="molName"></h2>
      <button id="molArchive" class="win-icon" type="button" title="存档" aria-label="存档"><span class="win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8"/><path d="M10 12h4"/></svg></span></button>
      <button id="molSaveImage" class="win-icon" type="button" title="保存图片到电脑" aria-label="保存图片到电脑"><span class="win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="15" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 14-5-5-9 9"/><path d="M19 15v5"/><path d="m16 18 3 3 3-3"/></svg></span></button>
      <button id="molSave" class="win-icon" type="button" title="下载到电脑" aria-label="下载到电脑">
        <span class="win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3v12"/><path d="m7 11 5 5 5-5"/><path d="M4 20h16"/></svg></span>
      </button>
      <button class="min-btn win-icon" type="button" title="最小化" aria-label="最小化"><span class="win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12h14"/></svg></span></button>
      <button class="restore-btn win-icon" type="button" title="还原" aria-label="还原"><span class="win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M3 11a9 9 0 1 1 2.6 6.4"/><path d="M3 5v6h6"/></svg></span></button>
      <button class="max-btn win-icon" type="button" title="放大到整个页面" aria-label="放大到整个页面">
        <span class="max-icon win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M7 17 17 7"/><path d="M9 7h8v8"/></svg></span>
        <span class="restore-icon win-glyph hidden" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M17 7 7 17"/><path d="M15 17H7V9"/></svg></span>
      </button>
      <button id="btnMolClose" class="win-icon close-icon" type="button" title="关闭" aria-label="关闭">
        <span class="win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></span>
      </button>
    </div>
    <div class="mol-canvas" id="molCanvas"></div>
    <div class="mol-tools" id="molTools">
      <span class="mol-tag">旋转</span>
      <span class="mol-dd" data-direction="up">
        <button id="molAxisBtn" class="mol-dd-btn" type="button" title="旋转轴" aria-haspopup="listbox">Z轴 ▲</button>
        <ul class="mol-dd-menu" id="molAxisMenu" role="listbox">
          <li role="option" data-value="x">X 轴</li>
          <li role="option" data-value="y">Y 轴</li>
          <li role="option" data-value="z" aria-selected="true">Z 轴</li>
        </ul>
      </span>
      <span class="mol-dd" data-direction="up">
        <button id="molAngleBtn" class="mol-dd-btn" type="button" title="旋转角度" aria-haspopup="listbox">45° ▲</button>
        <ul class="mol-dd-menu" id="molAngleMenu" role="listbox">
          <li role="option" data-value="15">15°</li>
          <li role="option" data-value="30">30°</li>
          <li role="option" data-value="45" aria-selected="true">45°</li>
          <li role="option" data-value="90">90°</li>
          <li role="option" data-value="180">180°</li>
        </ul>
      </span>
      <button id="molRotL" class="tool-icon" type="button" title="逆时针旋转" aria-label="逆时针旋转">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-7.7L3 8M3 3v5h5"/></svg>
      </button>
      <button id="molRotR" class="tool-icon" type="button" title="顺时针旋转" aria-label="顺时针旋转">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a9 9 0 1 1-3-7.7L21 8M21 3v5h-5"/></svg>
      </button>
      <span class="mol-sep"></span>
      <span class="mol-tag">缩放</span>
      <span class="mol-dd" data-direction="up">
        <button id="molZoomStepBtn" class="mol-dd-btn" type="button" title="缩放比例" aria-haspopup="listbox">1.25× ▲</button>
        <ul class="mol-dd-menu" id="molZoomStepMenu" role="listbox">
          <li role="option" data-value="1.1">1.1×</li>
          <li role="option" data-value="1.25" aria-selected="true">1.25×</li>
          <li role="option" data-value="1.5">1.5×</li>
          <li role="option" data-value="2">2×</li>
        </ul>
      </span>
      <button id="molZoomIn" class="tool-icon" type="button" title="放大" aria-label="放大">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M16 16l5 5M8 11h6M11 8v6"/></svg>
      </button>
      <button id="molZoomOut" class="tool-icon" type="button" title="缩小" aria-label="缩小">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M16 16l5 5M8 11h6"/></svg>
      </button>
      <span class="mol-sep"></span>
      <span class="mol-density-group hidden" id="molDensityGroup">
        <span class="mol-dd" data-direction="up">
          <button id="molDensityKindBtn" class="mol-dd-btn hidden" type="button" title="密度类型" aria-haspopup="listbox"></button>
          <ul class="mol-dd-menu" id="molDensityKindMenu" role="listbox"></ul>
        </span>
        <span class="mol-density-field" data-panel="molIsoPanel">
          <span class="mol-tag">等值面</span>
          <input type="number" id="molIsoValue" aria-label="等值面数值">
          <button type="button" class="mol-density-pop" title="调节等值面">▲</button>
          <div class="mol-density-panel" id="molIsoPanel">
            <div class="mol-density-track">
              <input type="range" id="molIsoRange" aria-label="等值面">
            </div>
            <div class="mol-density-val" id="molIsoValLabel">0.02</div>
          </div>
        </span>
        <span class="mol-density-field" data-panel="molOpacityPanel">
          <span class="mol-tag">透明度</span>
          <input type="number" id="molOpacityValue" min="0.05" max="1" step="0.05" value="0.6" aria-label="透明度数值">
          <button type="button" class="mol-density-pop" title="调节透明度">▲</button>
          <div class="mol-density-panel" id="molOpacityPanel">
            <div class="mol-density-track">
              <input type="range" id="molOpacityRange" min="0.05" max="1" step="0.05" value="0.6" aria-label="透明度">
            </div>
            <div class="mol-density-val" id="molOpacityValLabel">0.60</div>
          </div>
        </span>
      </span>
      <span class="mol-sep hidden" id="molDensitySep"></span>
      <span class="mol-player hidden" id="molPlayer">
        <button id="molPrev" class="tool-icon" type="button" title="上一帧" aria-label="上一帧">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4v16M20 4L9 12l11 8V4"/></svg>
        </button>
        <button id="molPlay" class="tool-icon" type="button" title="播放" aria-label="播放">
          <svg id="molPlayIcon" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5l12 7-12 7z"/></svg>
        </button>
        <button id="molNext" class="tool-icon" type="button" title="下一帧" aria-label="下一帧">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 4v16M4 4l11 8-11 8V4"/></svg>
        </button>
        <input type="range" id="molRange" min="0" max="0" value="0">
        <span class="mol-count" id="molCount">1 / 1</span>
        <span class="mol-dd" data-direction="up">
          <button id="molSpeedBtn" class="mol-dd-btn" type="button" title="播放速度" aria-haspopup="listbox">1× ▲</button>
          <ul class="mol-dd-menu" id="molSpeedMenu" role="listbox">
            <li role="option" data-value="0.5">0.5×</li>
            <li role="option" data-value="1" aria-selected="true">1×</li>
            <li role="option" data-value="2">2×</li>
            <li role="option" data-value="4">4×</li>
          </ul>
        </span>
      </span>
      <span class="mol-sep hidden" id="molPlayerSep"></span>
      <span class="mol-sep"></span>
      <button id="molPickClear" type="button" title="清除选中" aria-label="清除选中">清除选中</button>
      <button id="molProj">视角：正交</button>
      <button id="molReset">重置</button>
    </div>
    <div class="mol-pick-panel hidden" id="molPickPanel" role="dialog" aria-label="原子样式">
      <p class="mol-pick-title" id="molPickTitle">原子样式</p>
      <div class="mol-pick-row" id="molPickColorRow">
        <span>颜色</span><input type="color" id="molPickColor" value="#ff0000">
      </div>
      <div class="mol-pick-row" id="molPickSizeRow">
        <span>大小</span>
        <input type="number" id="molPickSize" min="0.05" max="0.80" step="0.01" value="0.30" aria-label="大小">
        <button class="mol-pick-num-btn" id="molPickSizeBtn" type="button" title="调节大小" aria-haspopup="true" aria-label="调节大小">▼</button>
        <div class="mol-pick-pop" id="molPickSizePop"><input type="range" id="molPickSizeRange" min="0.05" max="0.80" step="0.01" value="0.30" aria-label="大小滑杆"></div>
      </div>
      <div class="hidden" id="molPickStyleBox"></div>
      <div class="mol-pick-ops">
        <button id="molPickReset" type="button">恢复默认</button>
      </div>
    </div>
    <div class="mol-save hidden" id="molSaveBox">
      <div class="mol-save-win" role="dialog" aria-modal="true" aria-labelledby="molSaveTitle">
        <p id="molSaveTitle">保存图片</p>
        <div class="mol-save-options">
          <label for="molFormat">图片格式
            <select id="molFormat">
              <option value="png" selected>PNG</option>
              <option value="jpg">JPEG</option>
              <option value="webp">WebP</option>
            </select>
          </label>
          <label for="molScale">分辨率倍数
            <select id="molScale">
              <option value="1">1×</option>
              <option value="2">2×</option>
              <option value="4" selected>4×</option>
              <option value="6">6×</option>
              <option value="8">8×</option>
            </select>
          </label>
        </div>
        <label class="mol-save-name-label" for="molSaveName">文件名</label>
        <input id="molSaveName" type="text" spellcheck="false">
        <div class="mol-save-ops">
          <button id="molSaveCancel">取消</button>
          <button id="molSaveOk">保存</button>
        </div>
      </div>
    </div>
  </div>
</div>
<div class="mol-mask hidden" id="quickView" data-base-id="quickView">
  <div class="mol-win">
    <div class="mol-head">
      <h2 id="quickName"></h2>
      <button id="quickArchive" class="win-icon hidden" type="button" title="存档" aria-label="存档"><span class="win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8"/><path d="M10 12h4"/></svg></span></button>
      <button id="quickAction" class="win-icon hidden" type="button" title="下载到电脑" aria-label="下载到电脑">
        <span class="win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3v12"/><path d="m7 11 5 5 5-5"/><path d="M4 20h16"/></svg></span>
        <span class="action-text"></span>
      </button>
      <button class="min-btn win-icon" type="button" title="最小化" aria-label="最小化"><span class="win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12h14"/></svg></span></button>
      <button class="restore-btn win-icon" type="button" title="还原" aria-label="还原"><span class="win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M3 11a9 9 0 1 1 2.6 6.4"/><path d="M3 5v6h6"/></svg></span></button>
      <button id="btnQuickMax" class="max-btn win-icon" type="button" title="放大到整个页面" aria-label="放大到整个页面">
        <span class="max-icon win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M7 17 17 7"/><path d="M9 7h8v8"/></svg></span>
        <span class="restore-icon win-glyph hidden" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M17 7 7 17"/><path d="M15 17H7V9"/></svg></span>
      </button>
      <button id="btnQuickClose" class="win-icon close-icon" type="button" title="关闭" aria-label="关闭">
        <span class="win-glyph" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></span>
      </button>
    </div>
    <div id="quickBody"></div>
    <div class="mol-tools quick-tools hidden" id="quickPlayer">
      <span class="mol-player">
        <button id="mediaPlay" class="tool-icon" type="button" title="播放" aria-label="播放">
          <svg id="mediaPlayIcon" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5l12 7-12 7z"/></svg>
        </button>
        <input type="range" id="mediaRange" min="0" max="0" value="0" step="0.1" aria-label="播放进度">
        <span class="mol-count" id="mediaCount">0:00 / 0:00</span>
        <span class="mol-dd" data-direction="up">
          <button id="mediaSpeedBtn" class="mol-dd-btn" type="button" title="播放速度" aria-haspopup="listbox">1× ▲</button>
          <ul class="mol-dd-menu" id="mediaSpeedMenu" role="listbox">
            <li role="option" data-value="0.5">0.5×</li>
            <li role="option" data-value="1" aria-selected="true">1×</li>
            <li role="option" data-value="2">2×</li>
          </ul>
        </span>
        <button id="mediaMute" class="tool-icon" type="button" title="静音" aria-label="静音">
          <svg id="mediaMuteIcon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9H4M17 9l4 6M21 9l-4 6"/></svg>
        </button>
      </span>
    </div>
  </div>
</div>
<div class="file-menu hidden" id="fileMenu"></div>
<div class="confirm-mask hidden" id="confirmMask">
  <div class="confirm-box">
    <div class="confirm-head" id="confirmTitle">确认</div>
    <div class="confirm-body" id="confirmMessage"></div>
    <div class="confirm-foot">
      <button class="btn-cancel hidden" id="confirmExtra" type="button">不保存</button>
      <button class="btn-cancel" id="confirmCancel" type="button">取消</button>
      <button class="btn-ok" id="confirmOk" type="button">确定</button>
    </div>
  </div>
</div>
<div class="license-overlay hidden" id="licenseOverlay" role="dialog" aria-label="MIT License" aria-modal="false">
  <pre class="license-text" id="licenseText"></pre>
</div>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<script src="/assets/3dmol-min.js"></script>
<script src="/assets/xterm.js"></script>
<script>
/* ---------- 语言：简体中文 / English ---------- */
const LANG = (function () {
  const q = new URLSearchParams(location.search).get("lang");
  if (q) {
    const v = q.toLowerCase();
    if (v.indexOf("en") === 0) return "en";
    if (v.indexOf("zh") === 0) return "zh";
  }
  try {
    const saved = localStorage.getItem("mcta-lang");
    if (saved === "en" || saved === "zh") return saved;
  } catch (e) { /* 隐私模式忽略 */ }
  const tag = String(navigator.language || "").toLowerCase();
  const simp = tag === "zh" || tag === "zh-cn" || tag === "zh-hans" ||
    tag.indexOf("zh-cn-") === 0 || tag.indexOf("zh-hans-") === 0 ||
    tag === "zh-sg" || tag.indexOf("zh-sg-") === 0;
  return simp ? "zh" : "en";
})();
const IS_EN = LANG === "en";
try {
  if (new URLSearchParams(location.search).get("lang")) localStorage.setItem("mcta-lang", LANG);
} catch (e) { /* 隐私模式忽略 */ }

const I18N = {
  "McTa 文件服务": "McTa File Server",
  "格塔 · Meta Crystal Toolkit & Analysis": "Meta Crystal Toolkit & Analysis",
  "运行目录": "Run directory",
  "输入路径后回车切换目录": "Enter a path, then press Enter to switch directory",
  "进入": "Enter",
  "读取中…": "Loading…",
  "运行账户": "Run as",
  "终端": "Terminal",
  "终端窗口": "Terminal window",
  "最小化终端": "Minimize terminal",
  "最小化": "Minimize",
  "最大化终端": "Maximize terminal",
  "还原到侧栏": "Dock to sidebar",
  "还原大小": "Restore size",
  "点击终端顶端栏可浮动为小窗口": "Click the terminal header to open a floating window",
  "已复制选中文字": "Selection copied",
  "已粘贴剪切板内容": "Pasted from clipboard",
  "剪切板为空": "Clipboard is empty",
  "无法读取剪切板": "Clipboard access denied",
  "连接中…": "Connecting…",
  "正在连接终端…": "Connecting to terminal…",
  "新建目录": "New folder",
  "新建文本": "New text file",
  "其他文件": "Other files",
  "名称": "Name",
  "类型": "Type",
  "大小": "Size",
  "修改时间": "Modified",
  "此目录为空": "This directory is empty",
  "许可": "License",
  "查看许可": "View license",
  "MIT License · 源码与问题反馈：": "MIT License · Source and issues:",
  "· 源码与问题反馈：": " · Source and issues:",
  "旋转": "Rotate",
  "Z轴 ▲": "Z axis ▲",
  "X 轴": "X axis",
  "Y 轴": "Y axis",
  "Z 轴": "Z axis",
  "缩放": "Zoom",
  "等值面": "Isosurface",
  "透明度": "Opacity",
  "视角：正交": "View: orthographic",
  "视角：透视": "View: perspective",
  "重置": "Reset",
  "左键拖动旋转 · 滚轮缩放 · 中键拖动平移": "Left-drag to rotate · scroll to zoom · middle-drag to pan",
  "保存图片": "Save image",
  "保存图片到电脑": "Save image to computer",
  "存档": "Save state",
  "已存档": "State saved",
  "已存档 ": "Saved state ",
  "下载到电脑": "Download to computer",
  "尚未打开结构": "No structure is open",
  "不保存": "Don't save",
  "文件已修改": "File modified",
  "视图已调整": "3D view adjusted",
  "是否保存修改？": "Save changes?",
  "是否保存当前视图为图片？": "Save the current view as an image?",
  "是否存档修改？": "Save changes to state?",
  "是否存档当前视图？": "Save current view to state?",
  "图片格式": "Image format",
  "分辨率倍数": "Resolution scale",
  "文件名": "File name",
  "取消": "Cancel",
  "保存": "Save",
  "确认": "Confirm",
  "确定": "OK",
  "目录": "Folder",
  "文件": "File",
  "文本": "Text",
  "图片": "Image",
  "已连接": "Connected",
  "结构文件": "Structure",
  "文本 / 二进制": "Text / binary",
  "滚轮缩放 · 拖动平移": "Scroll to zoom · drag to pan",
  "下载": "Download",
  "已保存 ": "Saved ",
  "重命名 · ": "Rename · ",
  "名称不能为空": "Name cannot be empty",
  "已重命名为 ": "Renamed to ",
  "新建文本文件 · ": "New text file · ",
  "新建文本.txt": "untitled.txt",
  "输入文件名": "Enter a file name",
  "新建目录 · ": "New folder · ",
  "新建文件夹": "New folder",
  "输入目录名": "Enter a folder name",
  "请输入文件名": "Please enter a file name",
  "已创建 ": "Created ",
  "请输入目录名": "Please enter a folder name",
  "已创建目录 ": "Created folder ",
  "删除目录": "Delete folder",
  "删除文件": "Delete file",
  "确定删除 <b>": "Delete <b>",
  "</b> 吗？<br>此操作不可恢复。": "</b>?<br>This cannot be undone.",
  "删除": "Delete",
  "已删除 ": "Deleted ",
  "进入目录": "Open folder",
  "查看立体构型": "View 3D structure",
  "打开文本": "Open text",
  "查看图片": "View image",
  "打开": "Open",
  "重命名": "Rename",
  "该文件无法预览，长按可选择下载": "This file cannot be previewed; long-press to download",
  "该文件为二进制，无法在窗口中打开": "This binary file cannot be opened in the window",
  "暂停": "Pause",
  "播放": "Play",
  "静音": "Mute",
  "取消静音": "Unmute",
  "PDF": "PDF",
  "音频": "Audio",
  "视频": "Video",
  "表格": "Table",
  "Markdown": "Markdown",
  "空表格": "Empty table",
  "仅显示前 2000 行": "Only the first 2000 rows are shown",
  "当前浏览器不支持导出 ": "This browser cannot export ",
  "，请改用 PNG": "; use PNG instead",
  "已导出 ": "Exported ",
  "导出图片失败": "Failed to export image",
  "3Dmol 资源未加载，无法显示结构": "3Dmol failed to load; cannot show the structure",
  "当前浏览器不支持 WebGL，无法显示 3D 结构": "This browser does not support WebGL; cannot show the 3D structure",
  "连接中断，正在重试…": "Connection lost, retrying…",
  "已连接 · ": "Connected · ",
  "还原": "Restore",
  "放大": "Maximize",
  "缩回原始大小": "Restore original size",
  "放大到整个页面": "Maximize to full page",
  "还原弹窗": "Reset dialog",
  "关闭": "Close",
  "旋转轴": "Rotation axis",
  "旋转角度": "Rotation angle",
  "逆时针旋转": "Rotate counterclockwise",
  "顺时针旋转": "Rotate clockwise",
  "缩放比例": "Zoom step",
  "缩小": "Zoom out",
  "密度类型": "Density type",
  "等值面数值": "Isosurface value",
  "调节等值面": "Adjust isosurface",
  "透明度数值": "Opacity value",
  "调节透明度": "Adjust opacity",
  "上一帧": "Previous frame",
  "下一帧": "Next frame",
  "播放速度": "Playback speed",
  "清除选中": "Clear selection",
  "原子样式": "Atom style",
  "样式设置": "Style settings",
  "坐标轴设置": "Axis settings",
  "键与雾": "Bond & fog",
  "晶胞": "Cell",
  "坐标轴": "Axes",
  "轴颜色": "Axis colors",
  "深度雾": "Depth cue",
  "晶胞半径": "Cell radius",
  "晶胞虚线": "Cell dashed",
  "虚线段长": "Dash length",
  "虚线间隙": "Gap length",
  "晶胞颜色": "Cell color",
  "轴长度": "Axis length",
  "轴半径": "Axis radius",
  "箭头比例": "Arrow ratio",
  "箭头位置": "Arrow position",
  "轴透明度": "Axis opacity",
  "A 轴颜色": "A axis color",
  "B 轴颜色": "B axis color",
  "C 轴颜色": "C axis color",
  "调节键粗": "Adjust bond radius",
  "调节": "Adjust ",
  "滑杆": " slider",
  "调节大小": "Adjust size",
  "键粗滑杆": "Bond radius slider",
  "大小滑杆": "Size slider",
  "颜色": "Color",
  "大小": "Size",
  "键粗": "Bond radius",
  "测量": "Measurement",
  "标注字号": "Label size",
  "标注颜色": "Label color",
  "虚线连线": "Dashed line",
  "连线粗细": "Line width",
  "连线颜色": "Line color",
  "恢复默认": "Reset to default"
};

/* HTML 转义：文件名等不可信文本进入 innerHTML 前必须过一遍 */
function escHtml(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

/* ---- 浮窗预览：Markdown / 表格 / JSON / 媒体工具 ---- */
const QUICK_MD_EXTS = ["md", "markdown"];
const QUICK_TABLE_EXTS = ["csv", "tsv"];
const QUICK_TABLE_LIMIT = 2000;
let quickMedia = null;

function quickExt(name) {
  const s = String(name || "");
  const i = s.lastIndexOf(".");
  return i < 0 ? "" : s.slice(i + 1).toLowerCase();
}

function quickDockTag(data) {
  if (data.kind === "pdf") return tx("PDF");
  if (data.kind === "media") return tx(data.mediaType === "audio" ? "音频" : "视频");
  if (data.kind === "image") return tx("图片");
  const ext = quickExt(data.name);
  if (QUICK_MD_EXTS.indexOf(ext) >= 0) return tx("Markdown");
  if (QUICK_TABLE_EXTS.indexOf(ext) >= 0) return tx("表格");
  if (ext === "json") return "JSON";
  return tx("文本");
}

function mdInline(s) {
  let t = escHtml(s);
  t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
  t = t.replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>");
  t = t.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  t = t.replace(/\\*([^*]+)\\*/g, "<em>$1</em>");
  t = t.replace(/_([^_]+)_/g, "<em>$1</em>");
  t = t.replace(/\\[([^\\]]+)\\]\\(([^)\\s]+)\\)/g, function (m, label, href) {
    if (!/^(https?:\\/\\/|mailto:|\\/|#|\\.\\/)/i.test(href)) return m;
    return '<a href="' + href + '" target="_blank" rel="noopener noreferrer">' + label + "</a>";
  });
  return t;
}

function renderMarkdown(text) {
  const lines = String(text || "").replace(/\\r\\n?/g, "\\n").split("\\n");
  const out = [];
  let list = "";
  let code = false;
  function closeList() {
    if (list) { out.push("</" + list + ">"); list = ""; }
  }
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\\s*```/.test(line)) {
      closeList();
      if (code) { out.push("</code></pre>"); code = false; }
      else { out.push("<pre><code>"); code = true; }
      continue;
    }
    if (code) { out.push(escHtml(line) + "\\n"); continue; }
    if (!line.trim()) { closeList(); continue; }
    const h = line.match(/^(#{1,6})\\s+(.*)$/);
    if (h) {
      closeList();
      const n = h[1].length;
      out.push("<h" + n + ">" + mdInline(h[2]) + "</h" + n + ">");
      continue;
    }
    const ul = line.match(/^\\s*[-*+]\\s+(.*)$/);
    if (ul) {
      if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; }
      out.push("<li>" + mdInline(ul[1]) + "</li>");
      continue;
    }
    const ol = line.match(/^\\s*\\d+\\.\\s+(.*)$/);
    if (ol) {
      if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; }
      out.push("<li>" + mdInline(ol[1]) + "</li>");
      continue;
    }
    const q = line.match(/^\\s*>\\s?(.*)$/);
    if (q) { closeList(); out.push("<blockquote>" + mdInline(q[1]) + "</blockquote>"); continue; }
    closeList();
    out.push("<p>" + mdInline(line) + "</p>");
  }
  closeList();
  if (code) out.push("</code></pre>");
  return out.join("");
}

function parseDelimited(text, delim) {
  const s = String(text || "").replace(/\\r\\n?/g, "\\n");
  const rows = [];
  let row = [], cell = "", quoted = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (quoted) {
      if (c === '"') {
        if (s[i + 1] === '"') { cell += '"'; i++; }
        else quoted = false;
      } else cell += c;
      continue;
    }
    if (c === '"') { quoted = true; continue; }
    if (c === delim) { row.push(cell); cell = ""; continue; }
    if (c === "\\n") { row.push(cell); rows.push(row); row = []; cell = ""; continue; }
    cell += c;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

function renderDataTable(text, delim) {
  const rows = parseDelimited(text, delim);
  if (!rows.length) return '<p class="data-note">' + escHtml(tx("空表格")) + "</p>";
  const limit = Math.min(rows.length, QUICK_TABLE_LIMIT);
  const parts = ['<table class="data-table"><thead><tr>'];
  rows[0].forEach(function (cell) { parts.push("<th>" + escHtml(cell) + "</th>"); });
  parts.push("</tr></thead><tbody>");
  for (let i = 1; i < limit; i++) {
    parts.push("<tr>");
    rows[i].forEach(function (cell) { parts.push("<td>" + escHtml(cell) + "</td>"); });
    parts.push("</tr>");
  }
  parts.push("</tbody></table>");
  if (rows.length > limit) {
    parts.push('<div class="data-note">' + escHtml(tx("仅显示前 2000 行")) + "</div>");
  }
  return parts.join("");
}

function renderJsonValue(value) {
  if (value === null) return '<span class="json-null">null</span>';
  if (typeof value === "string") return '<span class="json-str">"' + escHtml(value) + '"</span>';
  if (typeof value === "number") return '<span class="json-num">' + escHtml(String(value)) + "</span>";
  if (typeof value === "boolean") return '<span class="json-bool">' + value + "</span>";
  if (Array.isArray(value)) {
    if (!value.length) return "[]";
    let out = '<details open><summary>[' + value.length + "]</summary>";
    value.forEach(function (v, i) {
      out += "<div>" + renderJsonValue(v) + (i < value.length - 1 ? "," : "") + "</div>";
    });
    return out + "</details>";
  }
  if (typeof value === "object") {
    const keys = Object.keys(value);
    if (!keys.length) return "{}";
    let out = '<details open><summary>{' + keys.length + "}</summary>";
    keys.forEach(function (k, i) {
      out += '<div><span class="json-key">"' + escHtml(k) + '":</span> ' +
        renderJsonValue(value[k]) + (i < keys.length - 1 ? "," : "") + "</div>";
    });
    return out + "</details>";
  }
  return escHtml(String(value));
}

function renderJsonTree(text) {
  try {
    return '<div class="json-view">' + renderJsonValue(JSON.parse(text)) + "</div>";
  } catch (err) {
    return '<pre class="json-view">' + escHtml(text) + "</pre>";
  }
}

function mediaTime(sec) {
  if (!isFinite(sec) || sec < 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return m + ":" + String(s).padStart(2, "0");
}

function setMediaPlayIcon(playing) {
  const icon = $("mediaPlayIcon");
  if (icon) icon.innerHTML = playing
    ? '<path d="M7 5h4v14H7zM13 5h4v14h-4z"/>'
    : '<path d="M7 5l12 7-12 7z"/>';
  const btn = $("mediaPlay");
  if (btn) {
    btn.title = tx(playing ? "暂停" : "播放");
    btn.setAttribute("aria-label", btn.title);
  }
}

function resetQuickMedia() {
  $("quickPlayer").classList.add("hidden");
  if (quickMedia) {
    try { quickMedia.pause(); quickMedia.removeAttribute("src"); quickMedia.load(); } catch (err) { /* 忽略 */ }
    quickMedia = null;
  }
  if ($("mediaSpeedBtn")) {
    $("mediaSpeedBtn").textContent = "1× ▲";
    setDDItem("mediaSpeedMenu", "1");
  }
  if ($("mediaMute")) {
    $("mediaMute").title = tx("静音");
    $("mediaMute").setAttribute("aria-label", $("mediaMute").title);
  }
}

function bindQuickMedia(media) {
  const range = $("mediaRange");
  const count = $("mediaCount");
  range.value = "0";
  range.max = "0";
  count.textContent = "0:00 / 0:00";
  setMediaPlayIcon(false);
  media.addEventListener("loadedmetadata", function () {
    range.max = String(isFinite(media.duration) ? media.duration : 0);
    range.value = String(media.currentTime || 0);
    count.textContent = mediaTime(media.currentTime) + " / " + mediaTime(media.duration);
  });
  media.addEventListener("timeupdate", function () {
    range.value = String(media.currentTime || 0);
    count.textContent = mediaTime(media.currentTime) + " / " + mediaTime(media.duration);
  });
  media.addEventListener("play", function () { setMediaPlayIcon(true); });
  media.addEventListener("pause", function () { setMediaPlayIcon(false); });
  media.addEventListener("ended", function () { setMediaPlayIcon(false); });
}

/* 动态文案：先精确匹配，再按最长前缀匹配（用于“已保存 ”+文件名这类拼接） */
function tx(s) {
  if (!IS_EN || !s) return s;
  if (Object.prototype.hasOwnProperty.call(I18N, s)) return I18N[s];
  let best = "";
  for (const key in I18N) {
    if (s.indexOf(key) === 0 && key.length > best.length) best = key;
  }
  return best ? I18N[best] + s.slice(best.length) : s;
}

(function initLangSwitch() {
  const btn = document.getElementById("langToggle");
  if (!btn) return;
  const label = btn.querySelector(".lang-name");
  const menu = document.getElementById("langMenu");
  const item = document.getElementById("langMenuItem");
  const next = LANG === "en" ? "zh" : "en";
  // 按钮显示当前语言，菜单只列出可切换到的另一种语言。
  if (label) label.textContent = LANG === "en" ? "English" : "中文";
  if (item) item.textContent = next === "en" ? "English" : "中文";
  btn.setAttribute("lang", LANG === "en" ? "en" : "zh-CN");
  btn.title = next === "en" ? "Switch to English" : "切换到中文";
  btn.setAttribute("aria-label", btn.title);
  function go() {
    try { localStorage.setItem("mcta-lang", next); } catch (e) { /* 隐私模式忽略 */ }
    const url = new URL(location.href);
    url.searchParams.set("lang", next);
    location.href = url.toString();
  }
  btn.onclick = function () {
    if (menu) menu.classList.toggle("open");
    btn.setAttribute("aria-expanded", menu && menu.classList.contains("open") ? "true" : "false");
  };
  if (item) item.onclick = function (ev) { ev.stopPropagation(); go(); };
  document.addEventListener("click", function (ev) {
    if (!menu || !btn) return;
    if (menu.contains(ev.target) || btn.contains(ev.target)) return;
    menu.classList.remove("open");
    btn.setAttribute("aria-expanded", "false");
  });
})();

(function applyLang() {
  if (!IS_EN) return;
  document.documentElement.lang = "en";
  document.title = tx(document.title);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
  let node;
  while ((node = walker.nextNode())) {
    const parent = node.parentNode;
    if (!parent || parent.nodeName === "SCRIPT" || parent.nodeName === "STYLE") continue;
    if (parent.closest && parent.closest(".lang-wrap")) continue;
    const raw = node.nodeValue;
    const key = raw ? raw.trim() : "";
    if (!key || !Object.prototype.hasOwnProperty.call(I18N, key)) continue;
    node.nodeValue = I18N[key];
  }
  ["title", "aria-label", "placeholder", "alt"].forEach(function (attr) {
    document.querySelectorAll("[" + attr + "]").forEach(function (el) {
      // 语言按钮的提示由 initLangSwitch 精确控制，不参与自动翻译，
      // 避免英文态下把“切换到中文”误替换为 “Switch to English”。
      if (el.id === "langToggle") return;
      const v = el.getAttribute(attr);
      if (v && Object.prototype.hasOwnProperty.call(I18N, v)) el.setAttribute(attr, I18N[v]);
    });
  });
})();

// 每个浏览器窗口持有独立的会话 ID，后端按它分配独立的终端进程与 cwd。
// window.name 在同一次页面加载（含刷新）中保持，新窗口/新标签则为空 → 新会话。
function mctaSessionId() {
  let sid = "";
  try {
    const named = String(window.name || "");
    if (named.indexOf("mcta-") === 0) sid = named.slice(5);
    if (!sid) sid = sessionStorage.getItem("mcta-sid") || "";
  } catch (err) { /* 隐私模式忽略 */ }
  const valid = function (v) { return /^[A-Za-z0-9_-]{1,64}$/.test(v || ""); };
  if (!valid(sid)) {
    try { sid = crypto.randomUUID(); } catch (err) { sid = ""; }
    if (!valid(sid)) {
      sid = "s" + Date.now().toString(36) + Math.random().toString(36).slice(2);
    }
  }
  try {
    window.name = "mcta-" + sid;
    sessionStorage.setItem("mcta-sid", sid);
  } catch (err) { /* 隐私模式忽略 */ }
  return sid;
}
const SESSION_ID = mctaSessionId();

const state = { root: "", cwd: "", viewing: null, user: null, term: null, es: null, cwdTimer: null, lastCwd: null, signature: "", watchTimer: null };
// 每个结构/轨迹/密度窗口独立持有自己的 viewer 与状态。
function freshMolCtx() {
  return { viewer: null, frames: 0, index: 0, timer: null, home: null,
           baseName: "", volume: null, isoShape: null, volumeGroups: null,
           ortho: true, saveJob: null, cell: null, cellShapes: [], structureModel: null,
           pickAtoms: [], measureShapes: [], measureLabels: [], styleAtom: null,
           atomStyles: {}, archive: null, sourcePath: "",
           pickMode: "atom", viewDirtyArmed: false };
}
let MC = freshMolCtx();
const MOL_BASE_MS = 220;  // 1× 速度下每帧间隔
const MOL_BOND_RADIUS = 0.06;  // 默认键半径（Å），空白处右键“样式设置”可调整
let molBondRadius = MOL_BOND_RADIUS;
let activeMask = null;
let maskSeq = 0;
const $ = function (id) {
  if (activeMask) {
    if (activeMask.id === id || activeMask.dataset.baseId === id) return activeMask;
    const scoped = activeMask.querySelector("#" + id);
    if (scoped) return scoped;
  }
  return document.getElementById(id);
};

// 浮窗层级：后显示或被选中的窗口置顶，不改变其它窗口的位置和大小。
// 最小化停靠图标使用独立的高位层级段：高于普通浮窗/菜单/提示，低于确认对话框遮罩(10000)。
let floatZ = 30;
const MIN_DOCK_Z = 9000;
let minDockZCount = MIN_DOCK_Z;
function bringFloatToFront(el) {
  if (!el) return;
  const isMin = el.classList.contains("win-min")
    || !!(el.querySelector && el.querySelector(".win-min"));
  if (isMin) { el.style.zIndex = String(++minDockZCount); return; }
  if (floatZ >= MIN_DOCK_Z - 2) floatZ = 30; // 普通层级接近停靠层时回卷，避免盖住最小化图标
  el.style.zIndex = String(++floatZ);
}

/* ---- 浮窗最小化停靠：主体隐藏、只留顶栏，停靠页面下方从左到右排列 ---- */
// 记录最小化顺序，终端浮窗与文件浮窗共用一条停靠栏。
const minDock = [];
// 标题变化会改变图标宽度，尺寸变化后重排，避免相邻图标重叠。
const minResizeObserver = (typeof ResizeObserver !== "undefined")
  ? new ResizeObserver(function () { requestAnimationFrame(layoutMinDock); }) : null;
// 兜底巡检：标题/尺寸被外部逻辑改写后也能在下一拍收敛，避免图标残留重叠或完整标题。
let minDockTick = null;
function startDockTick() {
  if (minDockTick !== null) return;
  minDockTick = setInterval(function () {
    if (!minDock.length) { clearInterval(minDockTick); minDockTick = null; return; }
    ensureDockTitles();
    layoutMinDock();
  }, 400);
}
function minDockAdd(el) {
  if (el && minDock.indexOf(el) < 0) {
    minDock.push(el);
    if (minResizeObserver) minResizeObserver.observe(el);
    startDockTick();
  }
}
function minDockRemove(el) {
  const i = minDock.indexOf(el);
  if (i >= 0) {
    minDock.splice(i, 1);
    if (minResizeObserver && minResizeObserver.unobserve) minResizeObserver.unobserve(el);
    // 清除停靠时的 !important 几何，后续 applyFree/resetFree/floatAt 才能重新定位。
    if (el && el.style) { el.style.removeProperty("left"); el.style.removeProperty("top"); }
    if (!minDock.length && minDockTick !== null) { clearInterval(minDockTick); minDockTick = null; }
  }
}
// 从打开记录或标题中提取纯文件名，避免停靠态残留大小/修改日期等信息。
function dockFileName(mask, h2) {
  const text = String(h2 ? h2.textContent : "");
  const key = String((mask && mask.dataset.openKey) || "");
  const m = /^(?:view|rename):(.+)$/.exec(key);
  if (m) {
    const name = m[1].replace(/\\\\/g, "/").split("/").filter(Boolean).pop();
    if (name) return name;
  }
  const parts = text.split(" · ");
  return (parts.length > 1 ? parts[0] : text).trim();
}
// 标题可能被其它逻辑写回完整信息，重排前统一收敛为纯文件名。
const dockTitleObserver = (typeof MutationObserver !== "undefined")
  ? new MutationObserver(function (muts) {
      for (let i = 0; i < muts.length; i++) {
        const t = muts[i].target;
        const el = t.nodeType === 3 ? t.parentElement : t;
        if (el && el.closest && el.closest(".mol-win.win-min")) {
          ensureDockTitles();
          layoutMinDock();
          break;
        }
      }
    }) : null;
function ensureDockTitles() {
  minDock.forEach(function (el) {
    if (!el || !el.classList.contains("win-min")) return;
    const mask = el.closest(".mol-mask");
    const h2 = mask && mask.querySelector(".mol-head h2");
    if (!h2) return;
    if (dockTitleObserver) {
      dockTitleObserver.observe(h2, { childList: true, characterData: true, subtree: true });
    }
    if (mask.dataset.fullTitle === undefined) mask.dataset.fullTitle = h2.textContent;
    const name = dockFileName(mask, h2);
    const tag = String(mask.dataset.dockTag || "");
    h2.dataset.dockName = tag ? name + " · " + tag : name; // CSS 停靠态只渲染该属性，可带类型标签
    if (h2.textContent !== name) h2.textContent = name;
  });
}
// 还原文件浮窗停靠栏中被精简的标题（停靠时只留文件名）。
function restoreDockTitle(mask) {
  const h2 = mask.querySelector(".mol-head h2");
  if (mask.dataset.fullTitle !== undefined) {
    if (h2) h2.textContent = mask.dataset.fullTitle;
    delete mask.dataset.fullTitle;
  }
  if (h2) delete h2.dataset.dockName;
}
// 从最小化停靠还原文件浮窗：恢复几何/标题，清理停靠位并重排。
function restoreMaskFromMin(mask) {
  if (!mask) return false;
  const win = mask.querySelector(".mol-win");
  if (!win || !win.classList.contains("win-min")) return false;
  win.classList.remove("win-min");
  minDockRemove(win);
  restoreDockTitle(mask);
  const saved = mask.dataset.minRect;
  if (saved && typeof mask._applyFree === "function") {
    try { mask._applyFree(JSON.parse(saved)); } catch (e) {}
  }
  delete mask.dataset.minRect;
  layoutMinDock();
  return true;
}
function layoutMinDock() {
  // 多个最小化图标紧贴左下角（图标间无间隙），终端固定在最左下；按实际宽度换行，不回拉造成重叠。
  ensureDockTitles();
  const ROW_H = 40, GAP = 0, EDGE = 4;
  const VW = window.innerWidth, VH = window.innerHeight;
  // 终端最小化时固定在最左下角；文件浮窗按剩余空间从左到右、自下而上逐行排列，不堆叠。
  const term = minDock.find(function (el) {
    return el && el.isConnected && el.classList.contains("win-min") && el.classList.contains("term-wrap");
  });
  const files = minDock.filter(function (el) {
    return el && el !== term && el.isConnected && el.classList.contains("win-min");
  });
  function place(el, x, row) {
    const w = Math.ceil(el.getBoundingClientRect().width || 120);
    // 用内联 !important 固定停靠几何，避免 maxed/free 等规则覆盖 left/top 造成重叠。
    el.style.setProperty("left", Math.round(Math.max(EDGE, x)) + "px", "important");
    el.style.setProperty("top", Math.round(VH - (row + 1) * ROW_H - row * GAP - EDGE) + "px", "important");
    return w;
  }
  // 终端占最底行最左
  if (term) place(term, EDGE, 0);
  let x = EDGE + (term ? Math.ceil(term.getBoundingClientRect().width || 120) + GAP : 0);
  let row = 0;
  for (let i = 0; i < files.length; i++) {
    const w = Math.ceil(files[i].getBoundingClientRect().width || 120);
    if (x > EDGE && x + w > VW - EDGE) { x = EDGE; row += 1; }
    x += place(files[i], x, row) + GAP;
  }
}
window.addEventListener("resize", layoutMinDock);
// 隐藏或移除停靠项时同步清理数组
const minDockObserver = new MutationObserver(function () {
  let changed = false;
  for (let i = minDock.length - 1; i >= 0; i--) {
    const el = minDock[i];
    if (!el.isConnected || !el.classList.contains("win-min")) { minDock.splice(i, 1); changed = true; }
  }
  if (changed) requestAnimationFrame(layoutMinDock);
});
minDockObserver.observe(document.body, { attributes: true, childList: true, subtree: true, attributeFilter: ["class"] });

// 复用隐藏窗口；没有可用窗口时从原始模板克隆一个。
// openKey 非空时，同一文件已打开则直接复用并置顶，不再克隆新窗口。
// cloneNode 不复制 .on* 处理器，这里按元素顺序补回去。
function acquireMask(baseId, openKey) {
  const all = document.querySelectorAll('.mol-mask[data-base-id="' + baseId + '"]');
  if (openKey) {
    for (let i = 0; i < all.length; i++) {
      if (!all[i].classList.contains("hidden") && all[i].dataset.openKey === openKey) {
        // 已打开但被最小化：再次点击同一文件时还原，并置于显示浮窗上层。
        const restored = restoreMaskFromMin(all[i]);
        switchMask(all[i]);
        bringFloatToFront(all[i]);
        if (restored && all[i].dataset.baseId === "molView" && MC.viewer) {
          requestAnimationFrame(function () { try { MC.viewer.resize(); MC.viewer.render(); } catch (e) {} });
        }
        return all[i];
      }
    }
  }
  for (let i = 0; i < all.length; i++) {
    if (all[i].classList.contains("hidden")) {
      if (baseId === "molView") all[i]._ctx = freshMolCtx();
      all[i].dataset.openKey = openKey || "";
      switchMask(all[i]);
      bringFloatToFront(all[i]);
      return all[i];
    }
  }
  const src = document.getElementById(baseId);
  const mask = src.cloneNode(true);
  mask.id = baseId + "-" + (++maskSeq);
  mask.dataset.openKey = openKey || "";
  document.body.appendChild(mask);
  const a = [src].concat(Array.prototype.slice.call(src.querySelectorAll("*")));
  const b = [mask].concat(Array.prototype.slice.call(mask.querySelectorAll("*")));
  for (let i = 0; i < a.length && i < b.length; i++) {
    for (const key in a[i]) {
      if (key.indexOf("on") === 0 && typeof a[i][key] === "function") b[i][key] = a[i][key];
    }
  }
  initModalFloating(mask);
  observeModal(mask);
  switchMask(mask);
  bringFloatToFront(mask);
  return mask;
}

function anyViewerOpen() {
  return !!document.querySelector(".mol-mask:not(.hidden)");
}

// 点击/聚焦任一弹窗时，后续 $() 与结构状态都指向该窗口。
function switchMask(next) {
  if (activeMask && activeMask.dataset.baseId === "molView") activeMask._ctx = MC;
  activeMask = next;
  if (next && next.dataset.baseId === "molView") MC = next._ctx || freshMolCtx();
}
["pointerdown", "focusin"].forEach(function (evt) {
  document.addEventListener(evt, function (e) {
    const floatEl = e.target.closest && e.target.closest(".mol-mask, .term-wrap.floating");
    if (!floatEl) return;
    bringFloatToFront(floatEl);
    if (floatEl.classList.contains("mol-mask")) switchMask(floatEl);
  }, true);
});

function toast(msg, err, anchor) {
  const el = $("toast");
  el.textContent = tx(msg);
  el.classList.toggle("err", !!err);
  const anchored = !!(anchor && (anchor.getBoundingClientRect || typeof anchor.clientX === "number"));
  el.classList.toggle("anchored", anchored);
  if (anchored) {
    // 警告贴着所点击的文件显示，并限制在视口内，避免被浮窗遮挡。
    let x, y;
    if (anchor.getBoundingClientRect) {
      const r = anchor.getBoundingClientRect();
      x = r.left + r.width / 2;
      y = r.top;
    } else {
      x = anchor.clientX;
      y = anchor.clientY;
    }
    const w = el.offsetWidth || 160;
    const h = el.offsetHeight || 36;
    el.style.left = Math.round(Math.max(w / 2 + 8, Math.min(window.innerWidth - w / 2 - 8, x))) + "px";
    el.style.top = Math.round(Math.max(h + 12, Math.min(window.innerHeight - 8, y - 8))) + "px";
    el.style.bottom = "auto";
  } else {
    el.style.left = "";
    el.style.top = "";
    el.style.bottom = "";
  }
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer = setTimeout(function () { el.classList.remove("show"); }, 2200);
}

function fmtSize(n) {
  if (n === null || n === undefined) return "";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
  return (n / 1073741824).toFixed(2) + " GB";
}

async function api(url, opts) {
  // 所有请求都带上窗口会话 ID：后端据此使用该窗口自己的终端目录做路径放行。
  const sep = url.indexOf("?") >= 0 ? "&" : "?";
  const res = await fetch(url + sep + "sid=" + q(SESSION_ID), opts || {});
  let data = {};
  try { data = await res.json(); } catch (e) { /* 非 JSON */ }
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function q(path) { return encodeURIComponent(path); }

// 图片/PDF/媒体/下载使用原生 <img>/<iframe>/window.open，不会经过 api()，
// 必须显式带上窗口会话 ID：否则后端按默认终端（cwd=运行目录）放行，
// 浏览到运行目录之外的目录（如 /mnt/d/test）时会被判为越界而 404。
function withSid(url) {
  const sep = url.indexOf("?") >= 0 ? "&" : "?";
  return url + sep + "sid=" + q(SESSION_ID);
}

function renderCrumbs() {
  const box = $("crumbs");
  box.innerHTML = "";
  const base = document.createElement("a");
  base.textContent = tx("运行目录");
  base.onclick = function () { load(""); };
  box.appendChild(base);
  const absolute = state.cwd.charAt(0) === "/";
  const parts = state.cwd ? state.cwd.split("/").filter(function (p) { return p; }) : [];
  let acc = "";
  parts.forEach(function (part) {
    const sep = document.createElement("span");
    sep.textContent = "/";
    box.appendChild(sep);
    if (absolute) {
      acc = acc + "/" + part;
    } else {
      acc = acc ? acc + "/" + part : part;
    }
    const link = document.createElement("a");
    link.textContent = part;
    const target = acc;
    link.onclick = function () { load(target); };
    box.appendChild(link);
  });
}

function showBrowser() {
  // 切换目录时把之前打开的文件（含克隆窗口）一起关闭并停掉播放。
  document.querySelectorAll(".mol-mask:not(.hidden)").forEach(function (m) {
    if (m.dataset.baseId === "molView") {
      const ctx = m._ctx;
      if (ctx) {
        if (ctx.timer) { clearInterval(ctx.timer); ctx.timer = null; }
        if (ctx.viewer) {
          try { ctx.viewer.clear(); } catch (err) { /* 忽略 */ }
          ctx.viewer = null;
        }
      }
    }
    m.classList.add("hidden");
  });
  MC = freshMolCtx();
  activeMask = null;
  state.viewing = null;
  $("browser").classList.remove("hidden");
}

// 页面导航到新目录后，把终端 cwd 同步到同一路径。
// 用 state.lastCwd（syncCwd 已记录终端真实 cwd）比较，避免来回 cd 形成循环。
function syncTermToDir(pathLabel) {
  if (!state.term || !pathLabel) return;
  const abs = absNormPath(pathLabel, "/");
  const cur = state.lastCwd ? absNormPath(state.lastCwd, "/") : "";
  if (cur && cur === abs) return;
  sendTermCd(abs).catch(function () { /* 终端不可用则忽略 */ });
}

function signatureOf(data) {
  return data.path + "|" + data.entries.map(function (entry) {
    return [entry.name, entry.dir ? 1 : 0, entry.kind, entry.size,
            entry.kind === "image" ? entry.ts : 0].join(":");
  }).join("|");
}

async function watchDir() {
  if (state.viewing || document.hidden) return;
  try {
    const data = await api("/api/list?path=" + q(state.cwd));
    if (signatureOf(data) === state.signature) return;
    await load(state.cwd, true);
  } catch (err) { /* 忽略目录监测错误 */ }
}

async function load(path, quiet) {
  // 真正切换目录前，先处理未保存的文本修改与已调整的 3D 视图。
  if (path !== state.cwd && dirtyMasks().length) {
    if (!(await resolveUnsaved())) return false;
  }
  try {
    const data = await api("/api/list?path=" + q(path));
    if (data.path !== state.cwd) closeMenu();
    state.cwd = data.path;
    state.signature = signatureOf(data);
    state.viewing = null;
    let basePath = data.root;
    while (basePath.length > 1 && basePath.endsWith("/")) { basePath = basePath.slice(0, -1); }
    if (basePath === "/") { basePath = ""; }
    let pathLabel;
    if (data.path.charAt(0) === "/") pathLabel = data.path;
    else pathLabel = data.path ? basePath + "/" + data.path : (basePath || "/");
    const pathInput = $("pathNote");
    pathInput.value = pathLabel;
    pathInput.dataset.label = pathLabel;
    renderCrumbs();
    showBrowser();

    const images = data.entries.filter(function (entry) {
      return !entry.dir && entry.kind === "image";
    });
    const others = data.entries.filter(function (entry) {
      return entry.dir || entry.kind !== "image";
    });

    const gallery = $("gallery");
    gallery.innerHTML = "";
    gallery.classList.toggle("hidden", images.length === 0);
    gallery.classList.toggle("g1", images.length === 1);
    gallery.classList.toggle("g2", images.length === 2);
    gallery.classList.toggle("g3", images.length >= 3);
    images.forEach(function (entry) {
      const tile = document.createElement("div");
      tile.className = "shot";
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = entry.name;
      img.src = withSid("/raw?path=" + q(entry.path)) + "&v=" + encodeURIComponent(entry.ts);
      const cap = document.createElement("span");
      cap.textContent = entry.name;
      tile.appendChild(img);
      tile.appendChild(cap);
      bindEntry(tile, entry);
      gallery.appendChild(tile);
    });
    $("othersLabel").classList.toggle("hidden", images.length === 0 || others.length === 0);

    const rows = $("fileTable");
    rows.innerHTML = "";
    others.forEach(function (entry) {
      const card = document.createElement("div");
      card.className = "entry";

      const wrap = document.createElement("div");
      wrap.className = "name";
      const label = document.createElement("span");
      label.className = "label";
      label.textContent = entry.name;
      wrap.appendChild(label);
      const tag = document.createElement("span");
      tag.className = "tag";
      const ext = quickExt(entry.name);
      const kindTag = entry.kind === "structure" ? "3D"
        : entry.kind === "pdf" ? tx("PDF")
        : entry.kind === "media" ? tx(entry.mediaType === "audio" ? "音频" : "视频")
        : entry.kind === "image" ? tx("图片")
        : QUICK_MD_EXTS.indexOf(ext) >= 0 ? tx("Markdown")
        : QUICK_TABLE_EXTS.indexOf(ext) >= 0 ? tx("表格")
        : ext === "json" ? "JSON" : tx("文件");
      tag.textContent = entry.dir ? tx("目录") : kindTag;
      wrap.appendChild(tag);
      card.appendChild(wrap);

      const meta = document.createElement("span");
      meta.className = "chip-meta";
      meta.textContent = fmtSize(entry.size) + " · " + entry.mtime;
      card.appendChild(meta);

      bindEntry(card, entry);
      rows.appendChild(card);
    });
    $("fileTable").classList.toggle("hidden", others.length === 0);
    $("empty").classList.toggle("hidden", data.entries.length > 0);
    // 点击目录/面包屑/右键进入目录后，让终端 cwd 跟随页面目录。
    syncTermToDir(pathLabel);
  } catch (err) {
    if (!quiet) toast(err.message, true);
  }
}

function setQuickAction(label, icon) {
  const action = $("quickAction");
  const text = tx(label);
  action.classList.toggle("win-icon", icon);
  action.querySelector(".win-glyph").classList.toggle("hidden", !icon);
  action.querySelector(".action-text").textContent = icon ? "" : text;
  action.title = text;
  action.setAttribute("aria-label", text);
}

// 新建目录/新建文本/重命名弹窗：顶栏只保留“存档”“关闭”两个按钮。
function setQuickDialogToolbar(onSave) {
  const view = $("quickView");
  const min = view.querySelector(".min-btn");
  const restore = view.querySelector(".restore-btn");
  if (min) min.classList.add("hidden");
  if (restore) restore.classList.add("hidden");
  $("btnQuickMax").classList.add("hidden");
  const action = $("quickAction");
  action.classList.add("hidden");
  action.onclick = null;
  const archive = $("quickArchive");
  archive.classList.remove("hidden");
  archive.disabled = false;
  archive.onclick = onSave;
}

// 普通文件预览弹窗：恢复最小化/还原按钮。
function resetQuickToolbar() {
  const view = $("quickView");
  const min = view.querySelector(".min-btn");
  const restore = view.querySelector(".restore-btn");
  if (min) min.classList.remove("hidden");
  if (restore) restore.classList.remove("hidden");
}

function closeQuick() {
  clearDirty($("quickView"));
  resetModalMax($("quickView"));
  $("quickView").classList.add("hidden");
  $("quickView").classList.remove("image-mode");
  $("quickView").classList.remove("preview");
  $("btnQuickMax").classList.remove("hidden");
  resetQuickToolbar();
  $("quickBody").innerHTML = "";
  resetQuickMedia();
  $("quickAction").onclick = null;
  $("quickAction").classList.add("hidden");
  $("quickArchive").onclick = null;
  $("quickArchive").classList.add("hidden");
  activeMask = null;
  if (!anyViewerOpen() && state.viewing) state.viewing = null;
}

function openQuick(path, data) {
  const mask = acquireMask("quickView", "view:" + path);
  clearDirty(mask);
  resetQuickToolbar();
  mask.dataset.dockTag = quickDockTag(data);
  state.viewing = path;
  $("quickView").classList.toggle("image-mode", data.kind === "image");
  $("quickView").classList.add("preview");
  $("quickName").textContent = data.name + " · " + fmtSize(data.size) + " · " + data.mtime;
  const body = $("quickBody");
  body.innerHTML = "";
  resetQuickMedia();
  const action = $("quickAction");
  action.classList.remove("hidden");
  action.disabled = false;
  const archive = $("quickArchive");
  archive.classList.add("hidden");
  archive.onclick = null;
  const rawUrl = withSid(data.url || ("/raw?path=" + q(path)));
  if (data.kind === "pdf") {
    const frame = document.createElement("iframe");
    frame.className = "pdf-frame";
    frame.title = data.name;
    frame.src = rawUrl + "#view=FitH";
    body.appendChild(frame);
    setQuickAction("下载到电脑", true);
    action.onclick = function () { window.open(rawUrl, "_blank"); };
  } else if (data.kind === "media") {
    let media;
    if (data.mediaType === "audio") {
      const view = document.createElement("div");
      view.className = "audio-view";
      view.innerHTML = '<div class="audio-glyph"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18V6l10-2v12M9 18a3 3 0 1 1-3-3c1.7 0 3 1.3 3 3zm10-2a3 3 0 1 1-3-3c1.7 0 3 1.3 3 3z"/></svg></div>' +
        "<div><div>" + escHtml(data.name) + '</div><div class="data-note">' + escHtml(tx("音频")) + "</div></div>";
      media = document.createElement("audio");
      media.preload = "metadata";
      media.src = rawUrl;
      view.appendChild(media);
      body.appendChild(view);
    } else {
      media = document.createElement("video");
      media.className = "quick-media";
      media.preload = "metadata";
      media.playsInline = true;
      media.src = rawUrl;
      body.appendChild(media);
    }
    quickMedia = media;
    $("quickPlayer").classList.remove("hidden");
    bindQuickMedia(media);
    setQuickAction("下载到电脑", true);
    action.onclick = function () { window.open(rawUrl, "_blank"); };
  } else if (data.kind === "image") {
    const box = document.createElement("div");
    box.className = "zoom-box";
    const img = document.createElement("img");
    img.src = rawUrl + "&v=" + Date.now();
    img.alt = data.name;
    img.draggable = false;
    box.appendChild(img);
    body.appendChild(box);
    bindImageZoom(box, img);
    setQuickAction("下载到电脑", true);
    action.onclick = function () { window.open(rawUrl, "_blank"); };
  } else {
    const ext = quickExt(data.name);
    if (QUICK_MD_EXTS.indexOf(ext) >= 0) {
      const view = document.createElement("div");
      view.className = "md-view";
      view.innerHTML = renderMarkdown(data.text || "");
      body.appendChild(view);
      setQuickAction("下载到电脑", true);
      action.onclick = function () { window.open(rawUrl, "_blank"); };
    } else if (QUICK_TABLE_EXTS.indexOf(ext) >= 0) {
      const view = document.createElement("div");
      view.innerHTML = renderDataTable(data.text || "", ext === "tsv" ? "\\t" : ",");
      body.appendChild(view);
      setQuickAction("下载到电脑", true);
      action.onclick = function () { window.open(rawUrl, "_blank"); };
    } else if (ext === "json") {
      body.innerHTML = renderJsonTree(data.text || "");
      setQuickAction("下载到电脑", true);
      action.onclick = function () { window.open(rawUrl, "_blank"); };
    } else {
      const area = document.createElement("textarea");
      area.value = data.text;
      area.spellcheck = false;
      area.addEventListener("input", function () {
        markDirty(mask, { type: "text", path: path, name: data.name });
      });
      area.addEventListener("keydown", function (event) {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
          event.preventDefault();
          saveQuick(path, data.name, area);
        }
      });
      body.appendChild(area);
      setQuickAction("下载到电脑", true);
      action.onclick = function () { window.open(rawUrl, "_blank"); };
      // 文本文件在下载按钮左边显示“存档”：保存修改到服务器
      archive.classList.remove("hidden");
      archive.onclick = function () { saveQuick(path, data.name, area); };
    }
  }
  $("quickView").classList.remove("hidden");
  const area = body.querySelector("textarea");
  if (area) {
    area.focus();
    area.setSelectionRange(0, 0);
    area.scrollTop = 0;
  }
}

function bindImageZoom(box, img) {
  let scale = 1;
  let ox = 0;
  let oy = 0;
  let drag = null;

  function apply() {
    img.style.transform = "translate(" + ox + "px," + oy + "px) scale(" + scale + ")";
  }

  box.addEventListener("wheel", function (event) {
    event.preventDefault();
    const rect = box.getBoundingClientRect();
    const cx = event.clientX - rect.left - rect.width / 2;
    const cy = event.clientY - rect.top - rect.height / 2;
    const next = Math.min(8, Math.max(0.2, scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15)));
    if (next === scale) return;
    const k = next / scale;
    ox = cx - k * (cx - ox);
    oy = cy - k * (cy - oy);
    scale = next;
    apply();
  }, {passive: false});

  box.addEventListener("pointerdown", function (event) {
    if (event.button !== 0) return;
    drag = {x: event.clientX - ox, y: event.clientY - oy};
    box.classList.add("dragging");
    box.setPointerCapture(event.pointerId);
  });
  box.addEventListener("pointermove", function (event) {
    if (!drag) return;
    ox = event.clientX - drag.x;
    oy = event.clientY - drag.y;
    apply();
  });
  function endDrag() {
    drag = null;
    box.classList.remove("dragging");
  }
  box.addEventListener("pointerup", endDrag);
  box.addEventListener("pointercancel", endDrag);

  box.addEventListener("dblclick", function () {
    scale = 1;
    ox = 0;
    oy = 0;
    apply();
  });
}

async function saveQuick(path, name, area) {
  const action = $("quickArchive");
  if (action) action.disabled = true;
  let saved = false;
  try {
    const data = await api("/api/file", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: path, text: area.value})
    });
    $("quickName").textContent = name + " · " + fmtSize(data.size) + " · " + data.mtime;
    const mask = area.closest && area.closest(".mol-mask");
    if (mask) clearDirty(mask);
    toast("已存档 " + data.path);
    saved = true;
  } catch (err) {
    toast(err.message, true);
  } finally {
    if (action) action.disabled = false;
  }
  return saved;
}

function openRename(entry) {
  acquireMask("quickView", "rename:" + entry.path);
  resetQuickMedia();
  $("quickView").classList.remove("image-mode");
  $("quickView").classList.remove("preview");
  state.viewing = entry.path;
  $("quickName").textContent = tx("重命名 · ") + entry.name;
  const body = $("quickBody");
  body.innerHTML = "";
  const input = document.createElement("input");
  input.className = "rename-input";
  input.value = entry.name;
  input.spellcheck = false;
  body.appendChild(input);
  setQuickDialogToolbar(function () { doRename(entry, input); });
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
      doRename(entry, input);
    }
  });
  $("quickView").classList.remove("hidden");
  input.focus();
  const dot = entry.name.lastIndexOf(".");
  if (dot > 0) input.setSelectionRange(0, dot);
  else input.select();
}

async function doRename(entry, input) {
  const name = input.value.trim();
  if (!name) { toast("名称不能为空", true); return; }
  if (name === entry.name) { closeQuick(); return; }
  const action = $("quickArchive");
  action.disabled = true;
  try {
    const data = await api("/api/rename", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: entry.path, name: name})
    });
    closeQuick();
    toast("已重命名为 " + data.name);
    await load(state.cwd, true);
  } catch (err) {
    toast(err.message, true);
    action.disabled = false;
  }
}

function openNewText() {
  acquireMask("quickView");
  resetQuickMedia();
  $("quickView").classList.remove("image-mode");
  $("quickView").classList.remove("preview");
  state.viewing = state.cwd || "/";
  $("quickName").textContent = tx("新建文本文件 · ") + (state.cwd || tx("运行目录"));
  const body = $("quickBody");
  body.innerHTML = "";
  const input = document.createElement("input");
  input.className = "rename-input";
  input.value = tx("新建文本.txt");
  input.spellcheck = false;
  input.placeholder = tx("输入文件名");
  body.appendChild(input);
  setQuickDialogToolbar(function () { createText(input); });
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
      createText(input);
    }
  });
  $("quickView").classList.remove("hidden");
  input.focus();
  input.setSelectionRange(0, input.value.lastIndexOf("."));
}

function openNewDir() {
  acquireMask("quickView");
  resetQuickMedia();
  $("quickView").classList.remove("image-mode");
  $("quickView").classList.remove("preview");
  state.viewing = state.cwd || "/";
  $("quickName").textContent = tx("新建目录 · ") + (state.cwd || tx("运行目录"));
  const body = $("quickBody");
  body.innerHTML = "";
  const input = document.createElement("input");
  input.className = "rename-input";
  input.value = tx("新建文件夹");
  input.spellcheck = false;
  input.placeholder = tx("输入目录名");
  body.appendChild(input);
  setQuickDialogToolbar(function () { createDir(input); });
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter") { event.preventDefault(); createDir(input); }
  });
  $("quickView").classList.remove("hidden");
  input.focus();
  input.select();
}

async function createText(input) {
  const name = input.value.trim();
  if (!name) { toast("请输入文件名", true); return; }
  const action = $("quickArchive");
  action.disabled = true;
  try {
    const data = await api("/api/new", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: state.cwd, name: name})
    });
    closeQuick();
    toast("已创建 " + data.name);
    await load(state.cwd, true);
    openFile(data.path, false);
  } catch (err) {
    toast(err.message, true);
    action.disabled = false;
  }
}

async function createDir(input) {
  const name = input.value.trim();
  if (!name) { toast("请输入目录名", true); return; }
  const action = $("quickArchive");
  action.disabled = true;
  try {
    const data = await api("/api/newdir", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: state.cwd, name: name})
    });
    closeQuick();
    toast("已创建目录 " + data.name);
    await load(state.cwd, true);
  } catch (err) {
    toast(err.message, true);
    action.disabled = false;
  }
}

function closeMenu() {
  const menu = $("fileMenu");
  if (menu.classList.contains("hidden")) return;
  menu.classList.add("hidden");
  menu.innerHTML = "";
}

function downloadFile(path) {
  window.open(withSid("/raw?path=" + q(path)), "_blank");
}

let confirmResolve = null;
function openConfirm(title, html, opts) {
  opts = opts || {};
  return new Promise(function (resolve) {
    confirmResolve = resolve;
    $("confirmTitle").textContent = tx(title || "确认");
    $("confirmMessage").innerHTML = html || "";
    const ok = $("confirmOk");
    ok.textContent = tx(opts.okText || "确定");
    ok.classList.toggle("danger", !!opts.danger);
    $("confirmCancel").textContent = tx(opts.cancelText || "取消");
    const extra = $("confirmExtra");
    if (extra) {
      extra.textContent = tx(opts.extraText || "不保存");
      extra.classList.toggle("hidden", !opts.extraText);
    }
    $("confirmMask").classList.remove("hidden");
  });
}
function closeConfirm(result) {
  const mask = $("confirmMask");
  if (mask.classList.contains("hidden")) return;
  mask.classList.add("hidden");
  if (confirmResolve) {
    confirmResolve(result);
    confirmResolve = null;
  }
}
$("confirmOk").onclick = function () { closeConfirm(true); };
$("confirmCancel").onclick = function () { closeConfirm(false); };
$("confirmExtra").onclick = function () { closeConfirm("extra"); };
$("confirmMask").addEventListener("click", function (ev) {
  if (ev.target === this) closeConfirm(false);
});
// 在全局 Escape 处理里也加确认弹窗
document.addEventListener("keydown", function (event) {
  if (event.key === "Escape" && confirmResolve) { closeConfirm(false); event.stopPropagation(); return; }
}, true);

/* ---- 未保存改动：文本编辑 / 3D 视图调整 ---- */
function maskDirty(mask) { return !!(mask && mask.dataset.dirty === "1"); }
function dirtyMasks() {
  return Array.prototype.slice.call(document.querySelectorAll(".mol-mask"))
    .filter(function (m) { return !m.classList.contains("hidden") && maskDirty(m); });
}
function markDirty(mask, info) {
  if (!mask) return;
  mask.dataset.dirty = "1";
  if (info) mask._unsaved = info;
}
function clearDirty(mask) {
  if (!mask) return;
  delete mask.dataset.dirty;
  delete mask._unsaved;
}
function maskOf(baseId) {
  if (activeMask && activeMask.dataset.baseId === baseId && !activeMask.classList.contains("hidden")) return activeMask;
  return document.querySelector('.mol-mask[data-base-id="' + baseId + '"]:not(.hidden)');
}
function molMarkViewDirty() {
  if (!MC || !MC.viewDirtyArmed) return;
  const mask = maskOf("molView");
  if (mask) markDirty(mask, { type: "view" });
}

let molSaveResolve = null;
function saveMolView() {
  const mask = maskOf("molView");
  if (!mask || !MC.viewer) return Promise.resolve(false);
  openMolSave();
  return new Promise(function (resolve) { molSaveResolve = resolve; });
}

// 逐个处理未保存窗口：返回 true 可继续关闭/切换，false 表示用户取消。
async function resolveUnsaved(list) {
  const masks = list || dirtyMasks();
  for (let i = 0; i < masks.length; i++) {
    const mask = masks[i];
    if (!maskDirty(mask)) continue;
    switchMask(mask);
    const info = mask._unsaved || {};
    if (mask.dataset.baseId === "molView") {
      const answer = await openConfirm("视图已调整", tx("是否存档当前视图？"),
        { okText: "存档", extraText: "不保存", cancelText: "取消" });
      if (answer === false) return false;
      if (answer === true && !(await molSaveArchive())) return false;
    } else {
      const answer = await openConfirm("文件已修改",
        tx("文件已修改") + "：" + escHtml(info.name || "") + "，" + tx("是否存档修改？"),
        { okText: "存档", extraText: "不保存", cancelText: "取消" });
      if (answer === false) return false;
      if (answer === true) {
        const area = mask.querySelector("textarea");
        if (area && !(await saveQuick(info.path || "", info.name || "", area))) return false;
      }
    }
    clearDirty(mask);
  }
  return true;
}

async function closeQuickWithConfirm() {
  const mask = maskOf("quickView");
  if (!mask) { closeQuick(); return; }
  if (!(await resolveUnsaved([mask]))) return;
  switchMask(mask);
  closeQuick();
}

async function closeStructureWithConfirm() {
  const mask = maskOf("molView");
  if (!mask) { closeStructure(); return; }
  if (!(await resolveUnsaved([mask]))) return;
  switchMask(mask);
  closeStructure();
}

window.addEventListener("beforeunload", function (ev) {
  if (!dirtyMasks().length) return;
  ev.preventDefault();
  ev.returnValue = "";
});

async function confirmDelete(entry) {
  const label = entry.dir ? "删除目录" : "删除文件";
  const ok = await openConfirm(tx(label),
    tx("确定删除 <b>") + escHtml(entry.name) + tx("</b> 吗？<br>此操作不可恢复。"),
    { danger: true, okText: "删除" });
  if (!ok) return;
  try {
    await api("/api/delete", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: entry.path})
    });
    toast("已删除 " + entry.name);
    await load(state.cwd, true);
  } catch (err) {
    toast(err.message, true);
  }
}

function openMenu(entry, x, y) {
  const menu = $("fileMenu");
  menu.innerHTML = "";
  function add(label, fn) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = tx(label);
    btn.onclick = function () { closeMenu(); fn(); };
    menu.appendChild(btn);
  }
  if (entry.dir) {
    add("进入目录", function () { load(entry.path); });
  } else if (entry.kind === "structure") {
    add("查看立体构型", function () { openStructure(entry.path); });
    add("打开文本", function () { openFile(entry.path, false); });
  } else if (entry.kind === "image") {
    add("查看图片", function () { openFile(entry.path, false); });
  } else {
    add("打开", function () { openFile(entry.path, false); });
  }
  add("重命名", function () { openRename(entry); });
  if (!entry.dir) add("下载", function () { downloadFile(entry.path); });
  add("删除", function () { confirmDelete(entry); });
  menu.classList.remove("hidden");
  const rect = menu.getBoundingClientRect();
  menu.style.left = Math.max(8, Math.min(x, window.innerWidth - rect.width - 8)) + "px";
  menu.style.top = Math.max(8, Math.min(y, window.innerHeight - rect.height - 8)) + "px";
}

function defaultAction(entry, anchor) {
  if (entry.dir) { load(entry.path); return; }
  if (entry.kind === "structure") { openStructure(entry.path, anchor); return; }
  openFile(entry.path, true, anchor);
}

function bindEntry(el, entry) {
  // 目录也支持长按菜单；单击进入目录/打开文件
  let pressTimer = null;
  let pressX = 0;
  let pressY = 0;
  let longPressed = false;

  function clearPress() {
    if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; }
  }

  el.addEventListener("pointerdown", function (event) {
    if (event.button !== 0) return;
    pressX = event.clientX;
    pressY = event.clientY;
    longPressed = false;
    clearPress();
    pressTimer = setTimeout(function () {
      pressTimer = null;
      longPressed = true;
    }, 550);
  });
  el.addEventListener("pointermove", function (event) {
    if (!pressTimer) return;
    if (Math.abs(event.clientX - pressX) > 8 || Math.abs(event.clientY - pressY) > 8) clearPress();
  });
  el.addEventListener("pointerup", function (event) {
    const held = longPressed;
    clearPress();
    if (held) {
      openMenu(entry, pressX, pressY);
      event.preventDefault();
    }
  });
  el.addEventListener("pointercancel", function () {
    longPressed = false;
    clearPress();
  });
  el.addEventListener("pointerleave", clearPress);
  el.addEventListener("click", function (event) {
    if (longPressed) {
      longPressed = false;
      event.stopImmediatePropagation();
      event.preventDefault();
      return;
    }
    defaultAction(entry, el);
  });
}

async function openFile(path, fromClick, anchor) {
  try {
    const data = await api("/api/file?path=" + q(path));
    if (["text", "image", "pdf", "media"].indexOf(data.kind) >= 0) {
      openQuick(path, data);
      return;
    }
    toast(fromClick ? "该文件无法预览，长按可选择下载" : "该文件为二进制，无法在窗口中打开", true, anchor);
  } catch (err) {
    toast(err.message, true, anchor);
  }
}

function hasWebGL() {
  try {
    const canvas = document.createElement("canvas");
    return !!(window.WebGLRenderingContext &&
      (canvas.getContext("webgl") || canvas.getContext("experimental-webgl")));
  } catch (err) {
    return false;
  }
}

function molLabel() {
  $("molCount").textContent = (MC.index + 1) + " / " + MC.frames;
  $("molRange").value = String(MC.index);
}

function showMolFrame(index) {
  if (!MC.viewer || MC.frames < 1) return;
  MC.index = ((index % MC.frames) + MC.frames) % MC.frames;
  MC.viewer.setFrame(MC.index);
  // 播放中跳过逐帧重建命中几何（会卡顿）；暂停后由 stopMolPlay 补注册。
  // 单步/拖动切帧时 MC.timer 已清空，这里立即给当前帧注册拾取。
  if (!MC.timer) molEnableFrameClickables();
  MC.viewer.render();
  // 轨迹播放：保留选中的原子，并按当前帧重新取坐标后重画测量，
  // 这样距离/角度会随帧实时变化；没有选中时无需重画。
  if ((MC.pickAtoms || []).length) molRefreshPicksForFrame();
  molLabel();
  molMarkViewDirty();
}

// 多帧轨迹切帧后重新给“当前帧”的原子注册点击回调。
// 3Dmol 的 setFrame 会把 model.atoms 换成对应帧的原子对象，而 setClickable
// 只给调用时的 this.atoms 打 clickable / intersectionShape 标记；不重新注册
// 的话新帧原子射线命中不到，就只能在第一帧选中原子测距/测角。
function molEnableFrameClickables() {
  if (!MC.viewer || !MC.viewer.setClickable || MC.frames < 1) return;
  try { MC.viewer.setClickable({}, true, molOnAtomClick); }
  catch (err) { /* 注册失败不影响切帧，仅该帧无法拾取 */ }
}

// 轨迹切帧后刷新测量：用保存的 model/index 从当前帧重新取原子对象
// （3Dmol 的 setFrame 会把该帧坐标写入 model.atoms，selectedAtoms 返回的就是更新后的引用），
// 再据此重算元素名、连线与距离/角度。取不到时退化为原对象，保持选中不丢。
function molRefreshPicksForFrame() {
  if (!MC.viewer || !(MC.pickAtoms || []).length) return;
  MC.pickAtoms = MC.pickAtoms.map(function (atom) {
    let cur = atom;
    try {
      if (MC.viewer.selectedAtoms && Number.isInteger(atom.index)) {
        const sel = { index: atom.index };
        if (atom.model !== undefined) sel.model = atom.model;
        const hits = MC.viewer.selectedAtoms(sel);
        if (hits && hits.length) cur = hits[0];
      }
    } catch (err) { /* 取帧失败时沿用原原子 */ }
    return cur;
  });
  molDrawMeasure();
}

function setMolPlayIcon(playing) {
  const svg = document.getElementById("molPlayIcon");
  if (!svg) return;
  if (playing) {
    svg.innerHTML = '<rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/>';
    $("molPlay").title = tx("暂停");
  } else {
    svg.innerHTML = '<path d="M7 5l12 7-12 7z"/>';
    $("molPlay").title = tx("播放");
  }
}

function stopMolPlay() {
  if (MC.timer) { clearInterval(MC.timer); MC.timer = null; }
  setMolPlayIcon(false);
  // 暂停在任意帧后，当前帧原子需要重新注册才能被点中（测距/测角）。
  molEnableFrameClickables();
}

function startMolPlay() {
  if (!MC.viewer || MC.frames < 2) return;
  stopMolPlay();
  setMolPlayIcon(true);
  const speed = Number(getMolSpeed()) || 1;
  const interval = Math.max(40, Math.round(MOL_BASE_MS / speed));
  MC.timer = setInterval(function () {
    if (!MC.viewer) { stopMolPlay(); return; }
    showMolFrame(MC.index + 1);
  }, interval);
}

// 晶胞：3Dmol 的 GL 线在 WebGL 下固定 1px（linewidth 不生效），
// 所以 12 条棱改用圆柱绘制，粗细由 cell.radius（Å）控制，线型由 cell.dashed 控制。
// 以下样式只保存在页面状态中，可在空白处右键的“样式设置”弹窗中调整，即时生效。
let molCellStyle = { radius: 0.015, dashed: true, dashLength: 0.25, gapLength: 0.25, color: "#0000FF" };
let molDepthCue = 0;  // 0 = 关闭深度雾，1 = 最强
// 轴箭头默认值：半径 0.06、不透明、红/绿/蓝三色，midpos 为负表示箭头位于末端前 |midpos| Å 处。
// length 为轴长倍率：默认 0.3；改小缩短、改大延长，即时生效。
let molAxisStyle = {
  radius: 0.06, headRatio: 1.618, midpos: -1, opacity: 1, length: 0.3,
  colors: ["#FF0000", "#00FF00", "#0000FF"]
};
// 测量标注样式：点击原子显示的元素名/距离/角度标签，以及相邻选中原子之间的连线。
// 可在空白处右键“样式设置 → 测量”分组中即时调整。
let molMeasureStyle = {
  fontSize: 18, fontColor: "#1b8a3f",
  lineRadius: 0.008, lineColor: "#e0553d",
  lineDashed: true, lineDashLength: 0.08, lineGapLength: 0.06
};
// gizmo 可见圆：半径 = 轴长滑杆上限对应的绘制半径 + x/y/z 标签占用长度。
// 画布半径取该值，保证任意旋转角度下最长轴的端点与标签都落在圆内，不被边缘裁切/遮挡。
const MOL_AXIS_LEN_MAX = 0.4;                                   // = MOL_STYLE_FIELDS AxisLength.max
const MOL_AXIS_R_SCALE = 160;                                   // 轴长 → 绘制半径映射
const MOL_AXIS_R_MAX = MOL_AXIS_LEN_MAX * MOL_AXIS_R_SCALE;      // 64：最长轴绘制半径
const MOL_AXIS_LABEL_OFFSET = 16;                               // 标签圆心外移轴端点的距离
const MOL_AXIS_LABEL_LEN = MOL_AXIS_LABEL_OFFSET + 8;            // 24：标签外移 + 半字高
const MOL_GIZMO_VISIBLE_R = MOL_AXIS_R_MAX + MOL_AXIS_LABEL_LEN; // 88：可见圆半径
// CSS 边长 = 可见圆直径 + 4px 抗锯齿余量；后备像素至少 2×（高清屏按 DPR 提升）保证清晰。
const MOL_GIZMO_SIZE = Math.ceil(MOL_GIZMO_VISIBLE_R * 2) + 4;   // 180

// “样式设置”弹窗字段：分组、标签、取值范围与实时生效函数。
// 这些条目可在页面 UI 直接调整，改动即时生效，无需重启服务。
const MOL_STYLE_GROUPS = [
  { key: "bond", label: "键与雾", fields: [
    { key: "BondRadius", id: "molPickBondRadius", label: "键粗", min: 0.02, max: 0.30, step: 0.01,
      get: function () { return molBondRadius; },
      set: function (v) { molBondRadius = v; molApplyBondRadius(); } },
    { key: "DepthCue", label: "深度雾", min: 0, max: 1, step: 0.01,
      get: function () { return molDepthCue; },
      set: function (v) { molDepthCue = v; molApplyDepthCue(); } }
  ] },
  { key: "cell", label: "晶胞", fields: [
    { key: "CellRadius", label: "晶胞半径", min: 0.005, max: 2, step: 0.005,
      get: function () { return molCellStyle.radius; },
      set: function (v) { molCellStyle.radius = v; molRedrawCell(); } },
    { key: "CellDashed", label: "晶胞虚线", type: "bool",
      get: function () { return molCellStyle.dashed; },
      set: function (v) { molCellStyle.dashed = v; molRedrawCell(); } },
    { key: "CellDashLength", label: "虚线段长", min: 0.01, max: 5, step: 0.01,
      get: function () { return molCellStyle.dashLength; },
      set: function (v) { molCellStyle.dashLength = v; molRedrawCell(); } },
    { key: "CellGapLength", label: "虚线间隙", min: 0.01, max: 5, step: 0.01,
      get: function () { return molCellStyle.gapLength; },
      set: function (v) { molCellStyle.gapLength = v; molRedrawCell(); } },
    { key: "CellColor", label: "晶胞颜色", type: "color",
      get: function () { return molCellStyle.color; },
      set: function (v) { molCellStyle.color = v; molRedrawCell(); } }
  ] },
  { key: "axis", label: "坐标轴", fields: [
    { key: "AxisLength", label: "轴长度", min: 0.06, max: 0.4, step: 0.01,
      get: function () { return molAxisStyle.length; },
      set: function (v) { molAxisStyle.length = v; molRedrawAxes(); } },
    { key: "AxisRadius", label: "轴半径", min: 0.05, max: 0.17, step: 0.005,
      get: function () { return molAxisStyle.radius; },
      set: function (v) { molAxisStyle.radius = v; molRedrawAxes(); } },
    { key: "AxisHeadRatio", label: "箭头比例", min: 1.62, max: 3.8, step: 0.01,
      get: function () { return molAxisStyle.headRatio; },
      set: function (v) { molAxisStyle.headRatio = v; molRedrawAxes(); } },
    { key: "AxisMidpos", label: "箭头位置", min: -5, max: 0.99, step: 0.01,
      get: function () { return molAxisStyle.midpos; },
      set: function (v) { molAxisStyle.midpos = v; molRedrawAxes(); } },
    { key: "AxisOpacity", label: "轴透明度", min: 0.35, max: 1, step: 0.01,
      get: function () { return molAxisStyle.opacity; },
      set: function (v) { molAxisStyle.opacity = v; molRedrawAxes(); } }
  ] },
  { key: "axisColor", label: "轴颜色", fields: [
    { key: "AxisColorA", label: "A 轴颜色", type: "color",
      get: function () { return molAxisStyle.colors[0]; },
      set: function (v) { molAxisStyle.colors[0] = v; molRedrawAxes(); } },
    { key: "AxisColorB", label: "B 轴颜色", type: "color",
      get: function () { return molAxisStyle.colors[1]; },
      set: function (v) { molAxisStyle.colors[1] = v; molRedrawAxes(); } },
    { key: "AxisColorC", label: "C 轴颜色", type: "color",
      get: function () { return molAxisStyle.colors[2]; },
      set: function (v) { molAxisStyle.colors[2] = v; molRedrawAxes(); } }
  ] },
  { key: "measure", label: "测量", fields: [
    { key: "MeasureFontSize", label: "标注字号", min: 8, max: 40, step: 1,
      get: function () { return molMeasureStyle.fontSize; },
      set: function (v) { molMeasureStyle.fontSize = v; molRedrawMeasure(); } },
    { key: "MeasureFontColor", label: "标注颜色", type: "color",
      get: function () { return molMeasureStyle.fontColor; },
      set: function (v) { molMeasureStyle.fontColor = v; molRedrawMeasure(); } },
    { key: "MeasureLineDashed", label: "虚线连线", type: "bool",
      get: function () { return molMeasureStyle.lineDashed; },
      set: function (v) { molMeasureStyle.lineDashed = v; molRedrawMeasure(); } },
    { key: "MeasureLineRadius", label: "连线粗细", min: 0.002, max: 0.05, step: 0.001,
      get: function () { return molMeasureStyle.lineRadius; },
      set: function (v) { molMeasureStyle.lineRadius = v; molRedrawMeasure(); } },
    { key: "MeasureLineColor", label: "连线颜色", type: "color",
      get: function () { return molMeasureStyle.lineColor; },
      set: function (v) { molMeasureStyle.lineColor = v; molRedrawMeasure(); } }
  ] }
];
const MOL_STYLE_FIELDS = MOL_STYLE_GROUPS.reduce(function (all, g) {
  return all.concat(g.fields);
}, []);
MOL_STYLE_FIELDS.forEach(function (f) {
  f.id = f.id || ("molSt" + f.key);
  f.def = f.get();
});

function molHexColor(v) {
  if (typeof v === "number") return "#" + ("000000" + v.toString(16)).slice(-6);
  return String(v || "#000000").slice(0, 7);
}

// 默认原子样式方案（来源见下）：
// · 颜色：参考 Materials Studio 的元素配色（MS 内置 CPK 色表，H 白 / C 灰 / N 蓝 / O 红 / S 黄 / Fe 橙），
//   为浅色背景把 H 等极亮色略微压暗，避免白底上完全看不见；
// · 半径：VESTA 的 atomic radii（金属/共价半径，单位 Å），球棍图按 VESTA 规则取 40%，
//   夹在 0.10–0.60 Å；VESTA 手册：球棍图的球半径 = 实际原子半径 × 40%。
const MOL_ATOM_COLORS = {
  H:"#dfe4ea", He:"#b3e3f5", Li:"#a066d9", Be:"#7acb00", B:"#e3a0a0", C:"#828282",
  N:"#3050f8", O:"#ff0d0d", F:"#7fbf50", Ne:"#80d1e3", Na:"#9154dd", Mg:"#5fbf00",
  Al:"#9f8a8a", Si:"#d0a878", P:"#f08a1a", S:"#e6d400", Cl:"#2fbf5f", Ar:"#6ab7cf",
  K:"#7f45c0", Ca:"#35b000", Ti:"#9aa2ab", V:"#8d93a0", Cr:"#7482b4", Mn:"#9a6fbe",
  Fe:"#e06633", Co:"#c96a86", Ni:"#45a045", Cu:"#b87939", Zn:"#6b78a8", Ga:"#b08080",
  Ge:"#6f8f8f", As:"#a873cf", Se:"#d98a00", Br:"#a33b3b", Kr:"#64abc4", Rb:"#7f3fba",
  Sr:"#25c000", Y:"#80d8d8", Zr:"#80c8c8", Nb:"#6bb0bb", Mo:"#54aaaa", Tc:"#459a9a",
  Ru:"#2d9090", Rh:"#227f8c", Pd:"#157089", Ag:"#a8b0b8", Cd:"#d0b585", In:"#a87b79",
  Sn:"#7f9090", Sb:"#9f6bb8", Te:"#c07b00", I:"#8a008a", Xe:"#5aa0b8", Cs:"#6b3aa8",
  Ba:"#20bd00", La:"#70c8ee", Ce:"#d8d8a8", Pr:"#b5d8a8", Nd:"#9fd8a8", Sm:"#8fd8a8",
  Eu:"#7fd8a8", Gd:"#6fd8a8", Tb:"#5fd8a8", Dy:"#52d8a8", Ho:"#44d0a0", Er:"#38c890",
  Tm:"#30bd78", Yb:"#28b060", Lu:"#22a858", Hf:"#5ab4e0", Ta:"#5aa0e0", W:"#3a90c8",
  Re:"#3f80a8", Os:"#3c7096", Ir:"#2f6488", Pt:"#9fa6bb", Au:"#d0a62c", Hg:"#a6aec4",
  Tl:"#a86b5e", Pb:"#707681", Bi:"#9f66b8", Po:"#a06200", At:"#8a6058", Rn:"#5a98aa",
  Th:"#2ab0e0", U:"#1f9fe0", Np:"#1f8fd8", Pu:"#1f7fc8"
};
const MOL_ATOM_RADII = {
  H:0.37, He:0.32, Li:1.52, Be:1.12, B:0.85, C:0.77, N:0.75, O:0.73, F:0.71, Ne:0.71,
  Na:1.86, Mg:1.60, Al:1.43, Si:1.18, P:1.10, S:1.04, Cl:0.99, Ar:0.98, K:2.27, Ca:1.97,
  Sc:1.62, Ti:1.47, V:1.36, Cr:1.28, Mn:1.27, Fe:1.24, Co:1.26, Ni:1.24, Cu:1.28, Zn:1.34,
  Ga:1.41, Ge:1.37, As:1.21, Se:1.16, Br:1.14, Kr:1.03, Rb:2.48, Sr:2.15, Y:1.78, Zr:1.60,
  Nb:1.46, Mo:1.39, Tc:1.36, Ru:1.34, Rh:1.34, Pd:1.37, Ag:1.44, Cd:1.51, In:1.67, Sn:1.50,
  Sb:1.41, Te:1.37, I:1.33, Xe:1.08, Cs:2.65, Ba:2.17, La:1.87, Ce:1.82, Pr:1.82, Nd:1.81,
  Sm:1.80, Eu:1.99, Gd:1.79, Tb:1.76, Dy:1.75, Ho:1.74, Er:1.73, Tm:1.72, Yb:1.94, Lu:1.72,
  Hf:1.56, Ta:1.46, W:1.39, Re:1.37, Os:1.35, Ir:1.36, Pt:1.39, Au:1.44, Hg:1.51, Tl:1.70,
  Pb:1.75, Bi:1.70, Po:1.40, At:1.50, Rn:1.50, Th:1.80, U:1.75, Np:1.75, Pu:1.75
};
// VESTA elements.ini 中的 atomic radius（金属/共价半径，Å）；球棍图按 40% 显示球半径。
function molElemKey(elem) {
  const s = String(elem || "").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : "";
}
function molDefaultColor(elem) {
  return MOL_ATOM_COLORS[molElemKey(elem)] || "#9aa4b2";
}
function molDefaultRadius(elem) {
  const r = MOL_ATOM_RADII[molElemKey(elem)];
  return Math.min(0.6, Math.max(0.1, (typeof r === "number" ? r : 0.9) * 0.4));
}

function molApplyDefaultAtomStyle() {
  if (!MC.viewer) return;
  // 3Dmol 的 setStyle 会先清空整组原子样式，后续 addStyle 才是在此基础上叠加。
  MC.viewer.setStyle({}, { stick: { radius: MOL_BOND_RADIUS },
    sphere: { color: "#9aa4b2", radius: molDefaultRadius("") } });
  Object.keys(MOL_ATOM_RADII).forEach(function (elem) {
    MC.viewer.addStyle({ elem: elem }, {
      sphere: { color: molDefaultColor(elem), radius: molDefaultRadius(elem) }
    });
  });
}

// 深度雾（Depth cue）强度 0–1：0 关闭；>0 时 fogStart 从 0.4 线性降到 0，
// fogEnd 从 1 降到 0.5，数值越大远处原子被雾遮得越明显。
function molApplyDepthCue() {
  if (!MC.viewer) return;
  const s = Math.min(1, Math.max(0, Number(molDepthCue) || 0));
  if (s <= 0) {
    MC.viewer.enableFog(false);
    return;
  }
  MC.viewer.enableFog({ fogStart: 0.4 * (1 - s), fogEnd: 1 - 0.5 * s });
  MC.viewer.render();
}

function molAxisSpec(color) {
  return {
    color: color, radius: molAxisStyle.radius, radiusRatio: molAxisStyle.headRatio,
    midpos: molAxisStyle.midpos, opacity: molAxisStyle.opacity
  };
}

function molCellPoints(cell) {
  const corner = function (a, b, c) {
    return {
      x: cell[0][0] * a + cell[1][0] * b + cell[2][0] * c,
      y: cell[0][1] * a + cell[1][1] * b + cell[2][1] * c,
      z: cell[0][2] * a + cell[1][2] * b + cell[2][2] * c
    };
  };
  const pts = [];
  for (let a = 0; a < 2; a++) {
    for (let b = 0; b < 2; b++) {
      for (let c = 0; c < 2; c++) pts.push(corner(a, b, c));
    }
  }
  return pts;
}

function drawMolCell(cell) {
  const pts = molCellPoints(cell);
  const shapes = [];
  [[0, 1], [0, 2], [0, 4], [1, 3], [1, 5], [2, 3], [2, 6], [3, 7],
   [4, 5], [4, 6], [5, 7], [6, 7]].forEach(function (edge) {
    try {
      const shape = MC.viewer.addCylinder({
        start: pts[edge[0]], end: pts[edge[1]], radius: molCellStyle.radius,
        color: molCellStyle.color, dashed: molCellStyle.dashed,
        dashLength: molCellStyle.dashLength, gapLength: molCellStyle.gapLength
      });
      if (shape) shapes.push(shape);
    } catch (err) { /* 忽略画线失败 */ }
  });
  return shapes;
}

// 左下角坐标轴指示器：只取主 viewer 的旋转四元数（getView 索引 4–7），
// 不取平移/缩放，因此轴只跟随结构旋转，长度恒为固定像素值，不会穿过原子。
function molQuatRotateVec(q, v) {
  const x = q[0] || 0, y = q[1] || 0, z = q[2] || 0, w = (typeof q[3] === "number" ? q[3] : 1);
  const tx = 2 * (y*v[2] - z*v[1]);
  const ty = 2 * (z*v[0] - x*v[2]);
  const tz = 2 * (x*v[1] - y*v[0]);
  return {
    x: v[0] + w*tx + (y*tz - z*ty),
    y: v[1] + w*ty + (z*tx - x*tz),
    z: v[2] + w*tz + (x*ty - y*tx)
  };
}

// 三条单位轴经四元数旋转后投影到屏幕（x 右、y 上），返回相对中心的偏移与深度。
function molGizmoAxisEnds(q, R) {
  return [[1,0,0], [0,1,0], [0,0,1]].map(function (v) {
    const r = molQuatRotateVec(q, v);
    // 归一化旋转结果：即使 getView 四元数带数值误差而非严格单位化，也保证端点 3D 长度恒为 R，
    // 从而 2D 投影恒 ≤ R、标签中心恒 ≤ R + 标签偏移，任何角度都不越出可见圆。
    const n = Math.sqrt(r.x*r.x + r.y*r.y + r.z*r.z) || 1;
    return { x: r.x/n*R, y: -r.y/n*R, z: r.z/n };
  });
}

function molGizmoQuat() {
  if (!MC.viewer || !MC.viewer.getView) return [0, 0, 0, 1];
  try {
    const v = MC.viewer.getView();
    if (v && v.length >= 8) return [v[4], v[5], v[6], v[7]];
  } catch (err) { /* 忽略 */ }
  return [0, 0, 0, 1];
}

// 坐标轴指示器：CSS 尺寸与后备像素常量见上方 MOL_GIZMO_SIZE / molGizmoScale。
let molGizmoPos = null;  // 用户拖动后的位置（相对画布左上角）；null = 默认左下角
function molGizmoScale() {
  const dpr = (typeof window !== "undefined" && window.devicePixelRatio) || 1;
  return Math.max(2, Math.min(3, dpr));
}

function molEnsureGizmo() {
  const host = $("molCanvas");
  if (!host) return null;
  let cv = host.querySelector(".mol-axis-gizmo");
  if (cv) return cv;
  cv = document.createElement("canvas");
  cv.className = "mol-axis-gizmo";
  cv.id = "molAxisGizmo";
  const s = molGizmoScale();
  cv.width = Math.round(MOL_GIZMO_SIZE * s);
  cv.height = Math.round(MOL_GIZMO_SIZE * s);
  cv.dataset.scale = String(s);
  cv.style.width = MOL_GIZMO_SIZE + "px";
  cv.style.height = MOL_GIZMO_SIZE + "px";
  cv.setAttribute("role", "img");
  cv.title = tx("坐标轴设置");

  function place(x, y) {
    const maxX = Math.max(0, (host.clientWidth || (MOL_GIZMO_SIZE + 24)) - MOL_GIZMO_SIZE);
    const maxY = Math.max(0, (host.clientHeight || (MOL_GIZMO_SIZE + 24)) - MOL_GIZMO_SIZE);
    const nx = Math.max(0, Math.min(maxX, x));
    const ny = Math.max(0, Math.min(maxY, y));
    cv.style.left = nx + "px";
    cv.style.top = ny + "px";
    cv.style.bottom = "auto";
    host._gizmoPos = { left: nx, top: ny };
    molGizmoPos = host._gizmoPos;
  }
  const saved = host._gizmoPos || molGizmoPos;
  if (saved) place(saved.left, saved.top);
  else {
    // 默认停靠左下角；CSS 初值一致，place() 会改写为具体 left/top 像素
    place(12, Math.max(0, (host.clientHeight || 0) - MOL_GIZMO_SIZE - 12));
  }

  let drag = null;
  cv.addEventListener("pointerdown", function (ev) {
    if (ev.button !== 0) return;  // 右键仍打开“坐标轴设置”
    ev.preventDefault();
    ev.stopPropagation();
    drag = {
      x: ev.clientX, y: ev.clientY,
      left: parseFloat(cv.style.left) || 0, top: parseFloat(cv.style.top) || 0
    };
    cv.classList.add("dragging");
    if (cv.setPointerCapture) { try { cv.setPointerCapture(ev.pointerId); } catch (err) {} }
  });
  cv.addEventListener("pointermove", function (ev) {
    if (!drag) return;
    ev.preventDefault();
    place(drag.left + (ev.clientX - drag.x), drag.top + (ev.clientY - drag.y));
  });
  function endDrag() {
    if (!drag) return;
    drag = null;
    cv.classList.remove("dragging");
  }
  cv.addEventListener("pointerup", endDrag);
  cv.addEventListener("pointercancel", endDrag);
  cv.addEventListener("contextmenu", function (ev) {
    ev.preventDefault();
    ev.stopPropagation();
    molOpenStylePanel(ev, "axis");
  });
  host.appendChild(cv);
  return cv;
}

// 画布尺寸变化后把指示器重新约束回可见区域。
function molClampGizmo() {
  const host = $("molCanvas");
  const cv = host && host.querySelector(".mol-axis-gizmo");
  if (!cv) return;
  const maxX = Math.max(0, (host.clientWidth || (MOL_GIZMO_SIZE + 24)) - MOL_GIZMO_SIZE);
  const maxY = Math.max(0, (host.clientHeight || (MOL_GIZMO_SIZE + 24)) - MOL_GIZMO_SIZE);
  const x = Math.max(0, Math.min(maxX, parseFloat(cv.style.left) || 0));
  const y = Math.max(0, Math.min(maxY, parseFloat(cv.style.top) || 0));
  cv.style.left = x + "px";
  cv.style.top = y + "px";
  host._gizmoPos = { left: x, top: y };
  molGizmoPos = host._gizmoPos;
}

function molHexRgba(hex, alpha) {
  const h = String(hex || "#000000").replace("#", "");
  const n = parseInt(h.length >= 6 ? h.slice(0, 6) : "000000", 16);
  return "rgba(" + ((n>>16)&255) + "," + ((n>>8)&255) + "," + (n&255) + "," + alpha + ")";
}

function molDrawAxisGizmo() {
  const cv = molEnsureGizmo();
  if (!cv || !cv.getContext) return;
  const ctx = cv.getContext("2d");
  if (!ctx) return;
  const s = Number(cv.dataset.scale) || molGizmoScale();
  const W = MOL_GIZMO_SIZE, H = MOL_GIZMO_SIZE, cx = W/2, cy = H/2;
  const R = Math.max(10, Math.min(MOL_AXIS_R_MAX, molAxisStyle.length * MOL_AXIS_R_SCALE));
  const rawEnds = molGizmoAxisEnds(molGizmoQuat(), R);
  // 保证任意旋转角度三条轴都可见：投影过短（轴几乎正对视线）时给一个最小可见长度，
  // 完全退化时按互成 120° 的固定方向展开，避免三轴与标签叠在圆心互相遮挡。
  const MIN_LEN = 11;
  const ends = rawEnds.map(function (e, i) {
    let x = e.x, y = e.y;
    const len = Math.sqrt(x * x + y * y);
    if (len < MIN_LEN) {
      if (len < 1e-4) {
        const a = (-90 + i * 120) * Math.PI / 180;
        x = Math.cos(a) * MIN_LEN;
        y = Math.sin(a) * MIN_LEN;
      } else {
        x = x / len * MIN_LEN;
        y = y / len * MIN_LEN;
      }
    }
    return { x: x, y: y, z: e.z };
  });
  // 逻辑坐标按 CSS 像素绘制，由变换放大到高清后备像素。
  if (ctx.setTransform) ctx.setTransform(s, 0, 0, s, 0, 0);
  else if (ctx.scale) { ctx.save(); ctx.scale(s, s); }
  ctx.clearRect(0, 0, W, H);
  const labels = ["x", "y", "z"];
  const order = [0, 1, 2].sort(function (a, b) { return ends[a].z - ends[b].z; });
  const lw = Math.max(1.5, Math.min(5, molAxisStyle.radius * 30));
  const head = Math.max(6, Math.min(14, 6 * molAxisStyle.headRatio / 1.618));
  // 1) 先画三条轴线（按深度从远到近），每条垫一层浅色描边，交叉处也能彼此分辨、不被盖住。
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  order.forEach(function (i) {
    const e = ends[i];
    // 远轴稍淡但始终清晰可见（最低 0.55），保证不被近轴完全盖住。
    const depthFade = 0.7 + 0.3 * Math.max(0, Math.min(1, (e.z + 1) / 2));
    const rgba = molHexRgba(molAxisStyle.colors[i],
      Math.max(0.55, Math.min(1, molAxisStyle.opacity * depthFade)));
    const ex = cx + e.x, ey = cy + e.y;
    const ang = Math.atan2(e.y, e.x);
    ctx.strokeStyle = "rgba(255,255,255,.92)";
    ctx.lineWidth = lw + 2.6;
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(ex, ey); ctx.stroke();
    ctx.strokeStyle = rgba; ctx.fillStyle = rgba; ctx.lineWidth = lw;
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(ex, ey); ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(ex, ey);
    ctx.lineTo(ex - head*Math.cos(ang - 0.42), ey - head*Math.sin(ang - 0.42));
    ctx.moveTo(ex, ey);
    ctx.lineTo(ex - head*Math.cos(ang + 0.42), ey - head*Math.sin(ang + 0.42));
    ctx.stroke();
  });
  // 2) 三个标签最后统一绘制，并垫浅色描边，保证任何角度都不被轴线或其他标签遮挡。
  const k = 1 + MOL_AXIS_LABEL_OFFSET / Math.max(R, 1);
  ctx.font = "700 14px ui-sans-serif, system-ui, sans-serif";
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  order.forEach(function (i) {
    const e = ends[i];
    const lx = cx + e.x*k, ly = cy + e.y*k;
    ctx.strokeStyle = "rgba(255,255,255,.95)"; ctx.lineWidth = 3.5;
    if (ctx.strokeText) ctx.strokeText(labels[i], lx, ly);
    ctx.fillStyle = molHexRgba(molAxisStyle.colors[i], Math.max(0.7, Math.min(1, molAxisStyle.opacity)));
    ctx.fillText(labels[i], lx, ly);
  });
  if (!ctx.setTransform && ctx.restore) ctx.restore();
}

// 样式设置改动后即时重画晶胞棱；轴相关改动即时重画左下角指示器。
function molRedrawCell() {
  if (!MC.viewer || !MC.cell) return;
  (MC.cellShapes || []).forEach(function (s) {
    try { MC.viewer.removeShape(s); } catch (err) { /* 忽略 */ }
  });
  MC.cellShapes = drawMolCell(MC.cell);
  MC.viewer.render();
}

function molRedrawAxes() { molDrawAxisGizmo(); }

// 正交 / 透视投影切换
function molSetProjection(ortho) {
  if (!MC.viewer) return;
  MC.ortho = !!ortho;
  MC.viewer.setProjection(MC.ortho ? "orthographic" : "perspective");
  $("molProj").textContent = MC.ortho ? tx("视角：正交") : tx("视角：透视");
  MC.viewer.show();
  molMarkViewDirty();
}

// 沿选定坐标轴按选定角度旋转；sign 为 1 顺时针、-1 逆时针（沿轴正向观察）
function molRotate(sign) {
  if (!MC.viewer) return;
  const axis = getMolAxis();
  const angle = getMolAngle();
  MC.viewer.rotate(sign * angle, axis, 0);
  MC.viewer.render();
  molMarkViewDirty();
}

// 原子拾取：左键选原子做距离/角度测量，右键打开单个原子的颜色/大小设置。
// 晶胞存在时用最小镜像换算键长与键角，避免跨边界原子得到虚假的长键。
function molInv3(m) {
  const a=m[0][0], b=m[0][1], c=m[0][2];
  const d=m[1][0], e=m[1][1], f=m[1][2];
  const g=m[2][0], h=m[2][1], i=m[2][2];
  const A=e*i-f*h, B=-(d*i-f*g), C=d*h-e*g;
  const det=a*A+b*B+c*C;
  if (Math.abs(det) < 1e-10) return null;
  return [[A/det, (c*h-b*i)/det, (b*f-c*e)/det],
          [B/det, (a*i-c*g)/det, -(a*f-c*d)/det],
          [C/det, -(a*h-b*g)/det, (a*e-b*d)/det]];
}

function molWrapVec(v) {
  const cell = MC.cell;
  if (!cell || cell.length < 3) return { x: v.x, y: v.y, z: v.z };
  const a = cell[0], b = cell[1], c = cell[2];
  const m = [[a[0], b[0], c[0]], [a[1], b[1], c[1]], [a[2], b[2], c[2]]];
  const inv = molInv3(m);
  if (!inv) return { x: v.x, y: v.y, z: v.z };
  const frac = [0, 0, 0];
  for (let k = 0; k < 3; k++) frac[k] = inv[k][0]*v.x + inv[k][1]*v.y + inv[k][2]*v.z;
  for (let k = 0; k < 3; k++) frac[k] -= Math.round(frac[k]);
  return {
    x: m[0][0]*frac[0] + m[0][1]*frac[1] + m[0][2]*frac[2],
    y: m[1][0]*frac[0] + m[1][1]*frac[1] + m[1][2]*frac[2],
    z: m[2][0]*frac[0] + m[2][1]*frac[1] + m[2][2]*frac[2]
  };
}

function molVecSub(a, b) { return { x: a.x-b.x, y: a.y-b.y, z: a.z-b.z }; }
function molVecAdd(a, b) { return { x: a.x+b.x, y: a.y+b.y, z: a.z+b.z }; }
function molVecMid(a, b) { return { x: (a.x+b.x)/2, y: (a.y+b.y)/2, z: (a.z+b.z)/2 }; }
function molVecLen(v) { return Math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z); }
function molAtomPos(a) { return { x: a.x, y: a.y, z: a.z }; }
function molAtomKey(a) { return String(a && a.model) + ":" + String(a && a.index); }

function molAngleDeg(a, b, c) {
  const ba = molWrapVec(molVecSub(a, b));
  const bc = molWrapVec(molVecSub(c, b));
  const la = molVecLen(ba), lc = molVecLen(bc);
  if (la < 1e-9 || lc < 1e-9) return 0;
  const dot = (ba.x*bc.x + ba.y*bc.y + ba.z*bc.z) / (la*lc);
  return Math.acos(Math.max(-1, Math.min(1, dot))) * 180 / Math.PI;
}

function molSelector(atom) {
  const sel = { index: atom.index };
  if (atom.model !== undefined) sel.model = atom.model;
  if (MC.frames > 0) sel.frame = MC.index;
  return sel;
}

function molClearGraphics() {
  if (MC.viewer) {
    for (let i = MC.measureLabels.length-1; i >= 0; i--) {
      try { MC.viewer.removeLabel(MC.measureLabels[i]); } catch (err) { /* 忽略 */ }
    }
    for (let i = MC.measureShapes.length-1; i >= 0; i--) {
      try { MC.viewer.removeShape(MC.measureShapes[i]); } catch (err) { /* 忽略 */ }
    }
  }
  MC.measureLabels = [];
  MC.measureShapes = [];
}

function molClearMeasure(skipRender) {
  molClearGraphics();
  MC.pickAtoms = [];
  molSyncClearButton();
  if (!skipRender && MC.viewer) MC.viewer.render();
}

function molAddPickLabel(pos, text) {
  if (!MC.viewer) return;
  try {
    const label = MC.viewer.addLabel(text, {
      position: pos, inFront: true, showBackground: false,
      fontColor: molMeasureStyle.fontColor, fontSize: molMeasureStyle.fontSize,
      borderThickness: 0
    });
    if (label) MC.measureLabels.push(label);
  } catch (err) { /* 忽略标签失败 */ }
}

function molAddPickLine(start, end) {
  if (!MC.viewer) return;
  try {
    const shape = MC.viewer.addCylinder({
      start: start, end: end, radius: molMeasureStyle.lineRadius,
      color: molMeasureStyle.lineColor,
      dashed: molMeasureStyle.lineDashed,
      dashLength: molMeasureStyle.lineDashLength, gapLength: molMeasureStyle.lineGapLength
    });
    if (shape) MC.measureShapes.push(shape);
  } catch (err) { /* 忽略连线失败 */ }
}

// 测量样式改动后即时重绘（保留选中原子，不清空）。
function molRedrawMeasure() {
  molDrawMeasure();
}

function molSyncClearButton() {
  const clear = $("molPickClear");
  if (clear) clear.disabled = (MC.pickAtoms || []).length === 0;
}

function molDrawMeasure() {
  molClearGraphics();
  const atoms = MC.pickAtoms;
  if (!MC.viewer || !atoms.length) { molSyncClearButton(); return; }
  // 元素名标在原子上方；选中的原子持续累加，直到点“清除选中”才全部消失。
  atoms.forEach(function (atom) {
    const p = molAtomPos(atom);
    const elem = String((atom && (atom.elem || atom.atom)) || "");
    molAddPickLabel({ x: p.x, y: p.y + 0.18, z: p.z }, elem);
  });
  // 相邻选中原子之间画细虚线并标距离。
  for (let i = 0; i + 1 < atoms.length; i++) {
    const start = molAtomPos(atoms[i]);
    const vec = molWrapVec(molVecSub(atoms[i+1], atoms[i]));
    const end = molVecAdd(start, vec);
    molAddPickLine(start, end);
    molAddPickLabel(molVecMid(start, end), molVecLen(vec).toFixed(3) + " Å");
  }
  // 每三个相邻选中原子以中间原子为顶点标角度。
  for (let i = 0; i + 2 < atoms.length; i++) {
    const b = molAtomPos(atoms[i+1]);
    const ba = molWrapVec(molVecSub(atoms[i], atoms[i+1]));
    const bc = molWrapVec(molVecSub(atoms[i+2], atoms[i+1]));
    const la = molVecLen(ba), lc = molVecLen(bc);
    const bis = { x: ba.x/la + bc.x/lc, y: ba.y/la + bc.y/lc, z: ba.z/la + bc.z/lc };
    const lb = molVecLen(bis);
    if (lb < 1e-6) { bis.x = 0; bis.y = 1; bis.z = 0; }
    else { bis.x /= lb; bis.y /= lb; bis.z /= lb; }
    molAddPickLabel(molVecAdd(b, { x: bis.x*0.55, y: bis.y*0.55, z: bis.z*0.55 }),
      molAngleDeg(atoms[i], atoms[i+1], atoms[i+2]).toFixed(1) + "°");
  }
  molSyncClearButton();
  MC.viewer.render();
}

function molColorHex(atom) {
  const sphere = atom && atom.style && atom.style.sphere;
  const color = sphere && sphere.color;
  if (typeof color === "number") return "#" + ("000000" + color.toString(16)).slice(-6);
  if (typeof color === "string" && color.charAt(0) === "#") return color.slice(0, 7);
  return molDefaultColor(atom && atom.elem);
}

function molClosePickPops() {
  const panel = $("molPickPanel");
  if (!panel) return;
  panel.querySelectorAll(".mol-pick-pop.show").forEach(function (p) { p.classList.remove("show"); });
  panel.querySelectorAll(".mol-pick-num-btn.active").forEach(function (b) { b.classList.remove("active"); });
}

// 3Dmol 的 targetedObjects 返回的是射线命中对象，真正的原子在 .clickable 上；
// 回调与测试夹具里传入的则直接是原子本身，这里统一取出可用原子。
function molResolveAtom(hit) {
  if (!hit) return null;
  const inner = hit.clickable;
  if (inner && typeof inner === "object" && typeof inner.index === "number") return inner;
  return typeof hit.index === "number" ? hit : null;
}

function molHidePickPanel() {
  const panel = $("molPickPanel");
  if (panel) panel.classList.add("hidden");
  molClosePickPops();
  MC.styleAtom = null;
  MC.pickMode = "atom";
}

function molNumValue(id, fallback, lo, hi) {
  const el = $(id);
  const v = Number(el && el.value);
  return isFinite(v) ? Math.min(hi, Math.max(lo, v)) : fallback;
}

function molSyncNumButton(id, value) {
  const range = $(id + "Range");
  if (range) range.value = String(value);
}

function molSetNumInputs(id, value) {
  const num = $(id);
  if (num) num.value = String(value);
  molSyncNumButton(id, value);
}

function molToggleNumPop(id, btn) {
  const pop = $(id + "Pop");
  const wasOpen = !!pop && pop.classList.contains("show");
  molClosePickPops();
  if (pop && !wasOpen) {
    pop.classList.add("show");
    if (btn) btn.classList.add("active");
  }
}

function molPositionPickPanel(ev, panel) {
  const win = $("molView") && $("molView").querySelector(".mol-win");
  if (!win) return;
  const rect = win.getBoundingClientRect();
  const cx = ev && typeof ev.clientX === "number" ? ev.clientX : rect.left + rect.width/2;
  const cy = ev && typeof ev.clientY === "number" ? ev.clientY : rect.top + rect.height/2;
  const w = panel.offsetWidth || 248;
  const h = panel.offsetHeight || 210;
  panel.style.left = Math.max(8, Math.min(cx - rect.left + 8, rect.width - w - 8)) + "px";
  // 顶部预留 132px，保证第一行数字框的小三角滑杆能在按钮上方完整弹出。
  panel.style.top = Math.max(132, Math.min(cy - rect.top + 8, rect.height - h - 8)) + "px";
}

// 按字段类型生成一行控件；数值框右侧的小三角按钮上方弹出滑杆。
function molMakeStyleRow(f) {
  const row = document.createElement("div");
  row.className = "mol-pick-row";
  const label = document.createElement("span");
  label.textContent = tx(f.label);
  row.appendChild(label);
  const input = document.createElement("input");
  input.id = f.id;
  input.setAttribute("aria-label", tx(f.label));
  if (f.type === "bool") {
    input.type = "checkbox";
    input.checked = !!f.get();
    input.onchange = function () { f.set(this.checked); molMarkViewDirty(); };
    row.appendChild(input);
    return row;
  }
  if (f.type === "color") {
    input.type = "color";
    input.value = molHexColor(f.get());
    input.oninput = function () { f.set(this.value); molMarkViewDirty(); };
    row.appendChild(input);
    return row;
  }
  input.type = "number";
  input.min = String(f.min);
  input.max = String(f.max);
  input.step = String(f.step);
  input.value = String(f.get());
  input.oninput = function () { molApplyStyleNumber(f, this.value, false); };
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "mol-pick-num-btn";
  btn.id = f.id + "Btn";
  btn.textContent = "▼";
  btn.title = tx("调节") + tx(f.label);
  btn.setAttribute("aria-haspopup", "true");
  btn.onclick = function () { molToggleNumPop(f.id, this); };
  const pop = document.createElement("div");
  pop.className = "mol-pick-pop";
  pop.id = f.id + "Pop";
  const range = document.createElement("input");
  range.type = "range";
  range.id = f.id + "Range";
  range.min = String(f.min);
  range.max = String(f.max);
  range.step = String(f.step);
  range.value = String(f.get());
  range.setAttribute("aria-label", tx(f.label) + tx("滑杆"));
  range.oninput = function () { molApplyStyleNumber(f, this.value, true); };
  pop.appendChild(range);
  row.appendChild(input);
  row.appendChild(btn);
  row.appendChild(pop);
  return row;
}

function molApplyStyleNumber(f, raw, fromRange) {
  let v = Number(raw);
  if (!isFinite(v)) v = f.get();
  v = Math.min(f.max, Math.max(f.min, v));
  const num = $(f.id);
  if (fromRange && num) num.value = String(v);
  molSyncNumButton(f.id, v);
  f.set(v);
  molMarkViewDirty();
}

function molBuildStylePanel(mode) {
  mode = mode === "axis" ? "axis" : "global";
  const box = $("molPickStyleBox");
  if (!box || box.dataset.mode === mode) return;
  box.dataset.mode = mode;
  box.innerHTML = "";
  // 空白右键：键与雾 + 晶胞 + 测量；坐标轴区域右键：坐标轴 + 轴颜色。
  const groups = MOL_STYLE_GROUPS.filter(function (g) {
    return mode === "axis"
      ? (g.key === "axis" || g.key === "axisColor")
      : (g.key === "bond" || g.key === "cell" || g.key === "measure");
  });
  const tabs = document.createElement("div");
  tabs.className = "mol-pick-tabs";
  groups.forEach(function (g, gi) {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.textContent = tx(g.label);
    if (gi === 0) tab.classList.add("active");
    tab.onclick = function () {
      tabs.querySelectorAll("button").forEach(function (b) { b.classList.remove("active"); });
      tab.classList.add("active");
      groups.forEach(function (gg) {
        const el = $("molPickGroup-" + gg.key);
        if (el) el.classList.toggle("hidden", gg.key !== g.key);
      });
    };
    tabs.appendChild(tab);
  });
  box.appendChild(tabs);
  groups.forEach(function (g, gi) {
    const group = document.createElement("div");
    group.className = "mol-pick-group" + (gi ? " hidden" : "");
    group.id = "molPickGroup-" + g.key;
    g.fields.forEach(function (f) { group.appendChild(molMakeStyleRow(f)); });
    box.appendChild(group);
  });
}

function molSyncStyleFields() {
  MOL_STYLE_FIELDS.forEach(function (f) {
    const el = $(f.id);
    if (!el) return;
    const v = f.get();
    if (f.type === "bool") el.checked = !!v;
    else if (f.type === "color") el.value = molHexColor(v);
    else molSetNumInputs(f.id, v);
  });
}

function molOpenPickPanel(atom, ev) {
  atom = molResolveAtom(atom);
  if (!atom) { molOpenStylePanel(ev); return; }
  MC.styleAtom = atom;
  MC.pickMode = "atom";
  const panel = $("molPickPanel");
  if (!panel) return;
  const title = $("molPickTitle");
  if (title) title.textContent = tx("原子样式");
  panel.setAttribute("aria-label", tx("原子样式"));
  const colorRow = $("molPickColorRow"), sizeRow = $("molPickSizeRow"), styleBox = $("molPickStyleBox");
  if (colorRow) colorRow.classList.remove("hidden");
  if (sizeRow) sizeRow.classList.remove("hidden");
  if (styleBox) styleBox.classList.add("hidden");
  const color = $("molPickColor");
  const sphere = atom && atom.style && atom.style.sphere;
  const sizeValue = sphere && typeof sphere.radius === "number" ? sphere.radius : (sphere && sphere.scale);
  if (color) color.value = molColorHex(atom);
  molSetNumInputs("molPickSize",
    Math.min(0.8, Math.max(0.05, Number(sizeValue) || molDefaultRadius(atom && atom.elem))));
  panel.classList.remove("hidden");
  molPositionPickPanel(ev, panel);
}

function molOpenStylePanel(ev, mode) {
  MC.styleAtom = null;
  MC.pickMode = "global";
  const isAxis = mode === "axis";
  const panelTitle = isAxis ? "坐标轴设置" : "样式设置";
  const panel = $("molPickPanel");
  if (!panel) return;
  const title = $("molPickTitle");
  if (title) title.textContent = tx(panelTitle);
  panel.setAttribute("aria-label", tx(panelTitle));
  const colorRow = $("molPickColorRow"), sizeRow = $("molPickSizeRow"), styleBox = $("molPickStyleBox");
  if (colorRow) colorRow.classList.add("hidden");
  if (sizeRow) sizeRow.classList.add("hidden");
  if (styleBox) styleBox.classList.remove("hidden");
  molBuildStylePanel(isAxis ? "axis" : "global");
  molSyncStyleFields();
  panel.classList.remove("hidden");
  molPositionPickPanel(ev, panel);
}

function molApplyAtomStyle() {
  const atom = molResolveAtom(MC.styleAtom);
  if (!atom || !MC.viewer) return;
  const colorEl = $("molPickColor");
  const radius = molNumValue("molPickSize", molDefaultRadius(atom.elem), 0.05, 0.8);
  const color = colorEl ? colorEl.value : molDefaultColor(atom.elem);
  molSyncNumButton("molPickSize", radius);
  MC.viewer.addStyle(molSelector(atom), { sphere: { color: color, radius: radius } });
  MC.viewer.render();
  MC.atomStyles[molAtomKey(atom)] = { model: atom.model, index: atom.index, elem: atom.elem, color: color, radius: radius };
  molMarkViewDirty();
}

function molResetAtomStyle() {
  const atom = molResolveAtom(MC.styleAtom);
  if (!atom || !MC.viewer) return;
  const color = molDefaultColor(atom.elem);
  const radius = molDefaultRadius(atom.elem);
  MC.viewer.addStyle(molSelector(atom), {
    sphere: { color: color, radius: radius }
  });
  const colorEl = $("molPickColor");
  if (colorEl) colorEl.value = color;
  molSetNumInputs("molPickSize", radius);
  delete MC.atomStyles[molAtomKey(atom)];
  MC.viewer.render();
  molMarkViewDirty();
}

// 键型固定为 3Dmol 原生 stick，“样式设置”只调整键粗。
function molApplyBondRadius() {
  if (!MC.viewer) return;
  MC.viewer.addStyle({}, { stick: { radius: molBondRadius } });
  MC.viewer.render();
  molMarkViewDirty();
}

function molResetPickSettings() {
  if (MC.pickMode === "global") {
    MOL_STYLE_FIELDS.forEach(function (f) { f.set(f.def); });
    molSyncStyleFields();
    return;
  }
  molResetAtomStyle();
}

function molOnContextMenu(ev) {
  ev.preventDefault();
  if (!MC.viewer) return;
  let atom = null;
  try {
    const xy = MC.viewer.mouseXY(ev.pageX, ev.pageY);
    const hits = MC.viewer.targetedObjects(xy.x, xy.y, MC.viewer.clickables) || [];
    if (hits.length) atom = molResolveAtom(hits[0]);
  } catch (err) { /* 拾取失败时按空白处处理 */ }
  if (atom) molOpenPickPanel(atom, ev);
  else molOpenStylePanel(ev);
}

function molOnAtomClick(atom, viewer, ev) {
  const button = ev && typeof ev.button === "number" ? ev.button : 1;
  if (button === 2) { molOpenPickPanel(atom, ev); return; }
  if (button !== 0) return;
  molHidePickPanel();
  const key = molAtomKey(atom);
  const at = MC.pickAtoms.findIndex(function (a) { return molAtomKey(a) === key; });
  if (at >= 0) MC.pickAtoms.splice(at, 1);
  else MC.pickAtoms.push(atom);
  molDrawMeasure();
}

function getDDValue(menuId) {
  const sel = document.querySelector('#' + menuId + ' li[aria-selected="true"]');
  return sel ? sel.getAttribute("data-value") : null;
}

function setDDItem(menuId, value) {
  const menu = document.getElementById(menuId);
  if (!menu) return;
  menu.querySelectorAll("li").forEach(function (li) {
    li.setAttribute("aria-selected", li.getAttribute("data-value") === value ? "true" : "false");
  });
}

function bindDD(btnId, menuId, formatLabel, onChange) {
  const btn = document.getElementById(btnId);
  const menu = document.getElementById(menuId);
  if (!btn || !menu) return;
  btn.onclick = function (ev) {
    ev.stopPropagation();
    const wrapper = btn.closest(".mol-dd");
    const wasOpen = wrapper.classList.contains("open");
    document.querySelectorAll(".mol-dd.open").forEach(function (d) { d.classList.remove("open"); });
    if (!wasOpen) wrapper.classList.add("open");
  };
  menu.addEventListener("click", function (ev) {
    const li = ev.target.closest("li");
    if (!li) return;
    ev.stopPropagation();
    const wrapper = this.closest(".mol-dd");
    const btnEl = wrapper.querySelector(".mol-dd-btn");
    this.querySelectorAll("li").forEach(function (item) { item.setAttribute("aria-selected", "false"); });
    li.setAttribute("aria-selected", "true");
    if (formatLabel) btnEl.textContent = formatLabel(li);
    else btnEl.textContent = li.textContent + " ▲";
    wrapper.classList.remove("open");
    if (onChange) onChange(li.getAttribute("data-value"));
  });
}

// 旋转下拉：X/Y/Z 轴、角度
function getMolAxis() { return getDDValue("molAxisMenu") || "y"; }
function getMolAngle() { return Number(getDDValue("molAngleMenu")) || 45; }
function getMolZoomStep() { return Number(getDDValue("molZoomStepMenu")) || 1.25; }
function getMolSpeed() { return Number(getDDValue("molSpeedMenu")) || 1; }
function setMolDensityKindItems(items, currentIndex) {
  const menu = document.getElementById("molDensityKindMenu");
  const btn = document.getElementById("molDensityKindBtn");
  if (!menu || !btn) return;
  menu.innerHTML = "";
  btn.classList.toggle("hidden", items.length <= 1);
  items.forEach(function (g, i) {
    const li = document.createElement("li");
    li.setAttribute("role", "option");
    li.setAttribute("data-value", String(i));
    li.textContent = g.label;
    if (i === currentIndex) li.setAttribute("aria-selected", "true");
    menu.appendChild(li);
  });
  const cur = menu.querySelector('li[aria-selected="true"]');
  btn.textContent = cur ? cur.textContent + " ▲" : "";
}
function getMolDensityKind() {
  return Number(getDDValue("molDensityKindMenu")) || 0;
}

bindDD("molAxisBtn", "molAxisMenu", function (li) {
  if (IS_EN) return li.textContent.replace(" axis", "") + " axis ▲";
  return li.textContent.replace(" 轴", "") + "轴 ▲";
});
bindDD("molAngleBtn", "molAngleMenu", function (li) { return li.textContent + " ▲"; });
bindDD("molZoomStepBtn", "molZoomStepMenu", function (li) { return li.textContent + " ▲"; });
bindDD("molSpeedBtn", "molSpeedMenu", function (li) { return li.textContent + " ▲"; }, function () {
  if (MC.timer) startMolPlay();
});
bindDD("molDensityKindBtn", "molDensityKindMenu", null, function (val) {
  switchMolDensityGroup(Number(val) || 0);
});
bindDD("mediaSpeedBtn", "mediaSpeedMenu", function (li) { return li.textContent + " ▲"; }, function (val) {
  if (quickMedia) quickMedia.playbackRate = Number(val) || 1;
});
$("mediaPlay").onclick = function () {
  if (!quickMedia) return;
  if (quickMedia.paused) {
    const p = quickMedia.play();
    if (p && p.catch) p.catch(function () {});
  } else quickMedia.pause();
};
$("mediaRange").oninput = function () {
  if (!quickMedia) return;
  const d = isFinite(quickMedia.duration) ? quickMedia.duration : 0;
  quickMedia.currentTime = Math.max(0, Math.min(d, Number(this.value) || 0));
};
$("mediaMute").onclick = function () {
  if (!quickMedia) return;
  quickMedia.muted = !quickMedia.muted;
  this.title = tx(quickMedia.muted ? "取消静音" : "静音");
  this.setAttribute("aria-label", this.title);
};

function molZoom(inward) {
  if (!MC.viewer) return;
  const step = Number(getMolZoomStep()) || 1.25;
  MC.viewer.zoom(inward ? step : 1 / step, 0);
  MC.viewer.render();
}

// “重置”回到未打开任何 _mcta.json 存档时的初始状态：
// 视图/相机、投影、帧、全局样式、逐原子样式、选中与测量、坐标轴指示器位置全部复位。
function resetMolView() {
  if (!MC.viewer) return;
  stopMolPlay();

  // 1) 全局样式字段恢复到页面初始值（MOL_STYLE_FIELDS 加载时已把 def 记为初始值）
  MOL_STYLE_FIELDS.forEach(function (f) { f.set(f.def); });
  molSyncStyleFields();

  // 2) 逐原子颜色/大小恢复默认
  MC.atomStyles = {};
  molApplyDefaultAtomStyle();

  // 3) 清除选中与测量标注
  molClearMeasure(true);
  MC.pickAtoms = [];
  molSyncClearButton();
  molHidePickPanel();

  // 4) 坐标轴指示器回到默认左下角
  molGizmoPos = null;
  const host = $("molCanvas");
  if (host) {
    host._gizmoPos = null;
    const cv = host.querySelector(".mol-axis-gizmo");
    if (cv) {
      cv.style.left = "12px";
      cv.style.top = Math.max(0, (host.clientHeight || 0) - MOL_GIZMO_SIZE - 12) + "px";
      cv.style.bottom = "auto";
    }
  }

  // 5) 投影 / 帧 / 相机视图复位到无存档时的 home
  molSetProjection(true);
  if (MC.frames > 1) {
    MC.index = 0;
    MC.viewer.setFrame(0);
    $("molRange").value = "0";
  }
  if (MC.home) {
    MC.viewer.setView(MC.home.view);
    if (MC.home.look && MC.viewer.lookingAt) {
      MC.viewer.lookingAt.copy(MC.home.look);
      MC.viewer.camera.lookAt(MC.viewer.lookingAt);
    }
  }

  MC.archive = null;
  MC.viewer.render();
  molLabel();
  molDrawAxisGizmo();
}

// 把当前画面导出为图片：PNG 保留透明背景，JPEG/WebP 先垫白底。
// factor > 1 时先把渲染尺寸放大再取图，得到更高分辨率的图。
function saveMolImage(factor, format, filename) {
  if (!MC.viewer) return;
  const ext = format === "jpg" ? "jpg" : format;
  const mime = format === "jpg" ? "image/jpeg" : format === "webp" ? "image/webp" : "image/png";
  const finish = function (uri) {
    const img = new Image();
    img.onload = function () {
      const canvas = document.createElement("canvas");
      canvas.width = img.width;
      canvas.height = img.height;
      const ctx = canvas.getContext("2d");
      if (mime !== "image/png") {
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
      }
      ctx.drawImage(img, 0, 0);
      const done = function (blob) {
        if (!blob || blob.type !== mime) {
          toast(tx("当前浏览器不支持导出 ") + ext.toUpperCase() + tx("，请改用 PNG"), true);
          return;
        }
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        toast("已导出 " + filename);
      };
      if (canvas.toBlob) canvas.toBlob(done, mime, 0.95);
      else done(null);
    };
    img.onerror = function () { toast("导出图片失败", true); };
    img.src = uri;
  };
  MC.viewer.render();
  if (factor <= 1) {
    finish(MC.viewer.pngURI());
    return;
  }
  // 临时放大渲染尺寸取图，再恢复原尺寸；上限 4096 像素，避免超出显卡视口限制
  const width = MC.viewer.WIDTH;
  const height = MC.viewer.HEIGHT;
  const ratio = width > 0 ? (MC.viewer.getCanvas().width / width) || 1 : 1;
  const cap = 4096;
  const mul = Math.max(1, Math.min(factor, cap / (width * ratio), cap / (height * ratio)));
  MC.viewer.setWidth(Math.round(width * mul));
  MC.viewer.setHeight(Math.round(height * mul));
  MC.viewer.render();
  const uri = MC.viewer.pngURI();
  MC.viewer.setWidth(width);
  MC.viewer.setHeight(height);
  MC.viewer.resize();
  MC.viewer.render();
  finish(uri);
}

// 保存前在弹窗中选择格式、分辨率倍数并确认文件名

function molSaveOptions() {
  const format = $("molFormat").value;
  const ext = format === "jpg" ? "jpg" : format;
  const factor = Math.max(1, Number($("molScale").value) || 1);
  const base = (MC.baseName || "structure").replace(/\\.[^.]+$/, "");
  const suffix = (MC.frames > 1 ? "-" + (MC.index + 1) : "") + "-" + factor + "x";
  return { factor: factor, format: format, ext: ext, filename: base + suffix + "." + ext };
}

function syncMolSaveName() {
  if (!MC.saveJob) return;
  MC.saveJob = molSaveOptions();
  $("molSaveName").value = MC.saveJob.filename;
}

function openMolSave() {
  if (!MC.viewer) return;
  MC.saveJob = molSaveOptions();
  $("molSaveName").value = MC.saveJob.filename;
  $("molSaveBox").classList.remove("hidden");
  $("molSaveName").focus();
  $("molSaveName").select();
}

function closeMolSave() {
  $("molSaveBox").classList.add("hidden");
  MC.saveJob = null;
  if (molSaveResolve) {
    const done = molSaveResolve;
    molSaveResolve = null;
    done(false);
  }
}

function confirmMolSave() {
  if (!MC.saveJob) { closeMolSave(); return; }
  const job = molSaveOptions();
  const typed = $("molSaveName").value.trim();
  const name = /\\.[^.\\/]+$/.test(typed) ? typed : (typed || "structure") + "." + job.ext;
  $("molSaveBox").classList.add("hidden");
  MC.saveJob = null;
  if (molSaveResolve) {
    const done = molSaveResolve;
    molSaveResolve = null;
    done(true);
  }
  saveMolImage(job.factor, job.format, name);
}

// ---- 3D 视图存档：旋转/平移/缩放、投影、帧、样式与原子标注 ----
// 存档文件名 = 结构文件名去掉扩展名 + "_mcta.json"，与结构同目录。
function molArchivePath(structPath) {
  const cleaned = String(structPath || "").replace(/\\\\/g, "/");
  const slash = cleaned.lastIndexOf("/");
  const dir = slash >= 0 ? cleaned.slice(0, slash + 1) : "";
  const name = slash >= 0 ? cleaned.slice(slash + 1) : cleaned;
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name;
  return dir + stem + "_mcta.json";
}

// 从当前 viewer 采集视图状态。getView() 为 [平移x,y,z, 缩放z, 四元数x,y,z,w]。
function molCaptureArchive() {
  const viewer = MC.viewer;
  if (!viewer) return null;
  const view = viewer.getView ? Array.prototype.slice.call(viewer.getView()) : null;
  const look = viewer.lookingAt
    ? [viewer.lookingAt.x, viewer.lookingAt.y, viewer.lookingAt.z] : null;
  const atoms = Object.keys(MC.atomStyles).map(function (key) {
    const s = MC.atomStyles[key];
    return { model: s.model, index: s.index, color: s.color, radius: s.radius };
  });
  const picks = (MC.pickAtoms || []).map(function (a) {
    return { model: a.model, index: a.index };
  });
  return {
    format: "mcta-view",
    version: 1,
    source: MC.baseName || "",
    saved: new Date().toISOString(),
    view: { matrix: view, lookingAt: look, ortho: !!MC.ortho, frame: MC.index || 0 },
    style: {
      bondRadius: molBondRadius,
      depthCue: molDepthCue,
      cell: {
        radius: molCellStyle.radius, dashed: molCellStyle.dashed,
        dashLength: molCellStyle.dashLength, gapLength: molCellStyle.gapLength,
        color: molCellStyle.color
      },
      axis: {
        radius: molAxisStyle.radius, headRatio: molAxisStyle.headRatio,
        midpos: molAxisStyle.midpos, opacity: molAxisStyle.opacity,
        length: molAxisStyle.length, colors: molAxisStyle.colors.slice()
      },
      measure: {
        fontSize: molMeasureStyle.fontSize, fontColor: molMeasureStyle.fontColor,
        lineRadius: molMeasureStyle.lineRadius, lineColor: molMeasureStyle.lineColor,
        lineDashed: molMeasureStyle.lineDashed,
        lineDashLength: molMeasureStyle.lineDashLength, lineGapLength: molMeasureStyle.lineGapLength
      },
      gizmoPos: molGizmoPos ? { left: molGizmoPos.left, top: molGizmoPos.top } : null
    },
    atoms: atoms,
    picks: picks
  };
}

async function molSaveArchive(anchor) {
  if (!MC.viewer) { toast(tx("尚未打开结构"), true, anchor); return false; }
  const path = molArchivePath(MC.sourcePath || state.viewing || MC.baseName || "structure");
  const stateObj = molCaptureArchive();
  try {
    await api("/api/file", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: path, text: JSON.stringify(stateObj, null, 2)})
    });
    MC.archive = stateObj;
    const mask = maskOf("molView");
    if (mask) clearDirty(mask);
    toast(tx("已存档") + " " + path, false, anchor);
    return true;
  } catch (err) {
    toast(err.message, true, anchor);
    return false;
  }
}

// 读取存档（读取失败/不存在时静默按默认显示）。
async function molLoadArchive(path) {
  if (!path) return null;
  try {
    const data = await api("/api/file?path=" + q(path));
    if (data && data.kind === "text" && typeof data.text === "string") {
      const arc = JSON.parse(data.text);
      if (arc && arc.format === "mcta-view" && arc.view) return arc;
    }
  } catch (err) { /* 无存档或格式无效：忽略 */ }
  return null;
}

// 把存档中的操作应用到当前已加载的结构上。
function molApplyArchive(arc) {
  if (!arc || !MC.viewer) return;
  const style = arc.style || {};
  if (typeof style.bondRadius === "number") molBondRadius = style.bondRadius;
  if (typeof style.depthCue === "number") molDepthCue = style.depthCue;
  const cell = style.cell || {};
  if (typeof cell.radius === "number") molCellStyle.radius = cell.radius;
  if (typeof cell.dashed === "boolean") molCellStyle.dashed = cell.dashed;
  if (typeof cell.dashLength === "number") molCellStyle.dashLength = cell.dashLength;
  if (typeof cell.gapLength === "number") molCellStyle.gapLength = cell.gapLength;
  if (typeof cell.color === "string") molCellStyle.color = cell.color;
  const axis = style.axis || {};
  ["radius", "headRatio", "midpos", "opacity", "length"].forEach(function (k) {
    if (typeof axis[k] === "number") molAxisStyle[k] = axis[k];
  });
  if (Array.isArray(axis.colors) && axis.colors.length === 3) molAxisStyle.colors = axis.colors.slice();
  const measure = style.measure || {};
  if (typeof measure.fontSize === "number") molMeasureStyle.fontSize = measure.fontSize;
  if (typeof measure.fontColor === "string") molMeasureStyle.fontColor = measure.fontColor;
  if (typeof measure.lineRadius === "number") molMeasureStyle.lineRadius = measure.lineRadius;
  if (typeof measure.lineColor === "string") molMeasureStyle.lineColor = measure.lineColor;
  if (typeof measure.lineDashed === "boolean") molMeasureStyle.lineDashed = measure.lineDashed;
  if (typeof measure.lineDashLength === "number") molMeasureStyle.lineDashLength = measure.lineDashLength;
  if (typeof measure.lineGapLength === "number") molMeasureStyle.lineGapLength = measure.lineGapLength;
  if (style.gizmoPos && typeof style.gizmoPos.left === "number") {
    molGizmoPos = { left: style.gizmoPos.left, top: style.gizmoPos.top };
  }
  // 恢复全局样式到 viewer
  molApplyDepthCue();
  molApplyBondRadius();
  if (MC.cell) molRedrawCell();
  molDrawAxisGizmo();
  molSyncStyleFields();
  // 恢复逐原子颜色/大小覆盖
  MC.atomStyles = {};
  (arc.atoms || []).forEach(function (o) {
    if (!Number.isInteger(o.index)) return;
    const sel = { index: o.index };
    if (o.model !== undefined) sel.model = o.model;
    const color = typeof o.color === "string" ? o.color : molDefaultColor("");
    const radius = typeof o.radius === "number" ? o.radius : molDefaultRadius("");
    MC.viewer.addStyle(sel, { sphere: { color: color, radius: radius } });
    MC.atomStyles[molAtomKey(sel)] = {
      model: o.model, index: o.index, color: color, radius: radius
    };
  });
  // 恢复投影与帧
  const view = arc.view || {};
  if (typeof view.ortho === "boolean") molSetProjection(view.ortho);
  if (MC.frames > 0 && Number.isInteger(view.frame)) {
    MC.index = Math.max(0, Math.min(MC.frames - 1, view.frame));
    MC.viewer.setFrame(MC.index);
    $("molRange").value = String(MC.index);
    molLabel();
  }
  // 恢复旋转/平移/缩放
  if (Array.isArray(view.matrix) && view.matrix.length === 8 && MC.viewer.setView) {
    MC.viewer.setView(view.matrix);
  }
  if (Array.isArray(view.lookingAt) && view.lookingAt.length === 3 && MC.viewer.lookingAt) {
    MC.viewer.lookingAt.x = view.lookingAt[0];
    MC.viewer.lookingAt.y = view.lookingAt[1];
    MC.viewer.lookingAt.z = view.lookingAt[2];
    if (MC.viewer.camera && MC.viewer.camera.lookAt) MC.viewer.camera.lookAt(MC.viewer.lookingAt);
  }
  // 恢复标注（选中的原子 → 元素名/距离/角度）
  MC.pickAtoms = [];
  (arc.picks || []).forEach(function (p) {
    if (!Number.isInteger(p.index)) return;
    let sel = { index: p.index };
    if (p.model !== undefined) sel.model = p.model;
    let atoms = [];
    try { atoms = MC.viewer.selectedAtoms ? MC.viewer.selectedAtoms(sel) : []; } catch (err) { atoms = []; }
    if (atoms && atoms.length) MC.pickAtoms.push(atoms[0]);
  });
  molDrawMeasure();
  MC.viewer.render();
  molDrawAxisGizmo();
}

function updateMolIsosurface() {
  if (!MC.viewer || !MC.volume) return;
  if (MC.isoShape) {
    MC.viewer.removeShape(MC.isoShape);
    MC.isoShape = null;
  }
  const isoval = Number($("molIsoValue").value);
  const opacity = Number($("molOpacityValue").value);
  if (!Number.isFinite(isoval) || !Number.isFinite(opacity)) return;
  MC.isoShape = MC.viewer.addIsosurface(MC.volume, {
    isoval: isoval, opacity: opacity, color: "#3b82f6"
  });
  MC.viewer.render();
}

function configureMolDensity(data) {
  MC.volume = null;
  MC.isoShape = null;
  closeMolDensityPanels();
  $("molDensityGroup").classList.add("hidden");
  $("molDensitySep").classList.add("hidden");
  const groups = data.densities;
  if (!Array.isArray(groups) || !groups.length) return;
  setMolDensityKindItems(groups, 0);
  MC.volumeGroups = groups.map(function (g) {
    return {
      volume: new $3Dmol.VolumeData(g.cube, "cube"),
      options: g.options,
    };
  });
  switchMolDensityGroup(0);
  $("molDensityGroup").classList.remove("hidden");
  $("molDensitySep").classList.remove("hidden");
}

function switchMolDensityGroup(index) {
  if (!MC.volumeGroups || !MC.volumeGroups[index]) return;
  MC.volume = MC.volumeGroups[index].volume;
  const options = MC.volumeGroups[index].options;
  const isoRange = $("molIsoRange");
  const isoNumber = $("molIsoValue");
  isoRange.min = isoNumber.min = String(options.min);
  isoRange.max = isoNumber.max = String(options.max);
  isoRange.step = isoNumber.step = String(options.step);
  isoRange.value = String(options.value);
  isoNumber.value = isoRange.value;
  $("molOpacityRange").min = "0.05";
  $("molOpacityRange").max = "1";
  $("molOpacityRange").step = "0.05";
  $("molOpacityRange").value = "0.6";
  $("molOpacityValue").min = "0.05";
  $("molOpacityValue").max = "1";
  $("molOpacityValue").step = "0.05";
  $("molOpacityValue").value = "0.6";
  $("molIsoValLabel").textContent = Number(isoRange.value).toPrecision(4);
  $("molOpacityValLabel").textContent = Number($("molOpacityRange").value).toFixed(2);
  updateMolIsosurface();
}

function closeMolDensityPanels() {
  document.querySelectorAll(".mol-density-panel.show").forEach(function (p) {
    p.classList.remove("show");
  });
  document.querySelectorAll(".mol-density-pop.active").forEach(function (b) {
    b.classList.remove("active");
  });
}

function setMolPlayerVisible(on) {
  $("molPlayer").classList.toggle("hidden", !on);
  $("molPlayerSep").classList.toggle("hidden", !on);
}

function closeStructure() {
  clearDirty($("molView"));
  stopMolPlay();
  molHidePickPanel();
  if (MC.saveJob) closeMolSave();
  resetModalMax($("molView"));
  MC.frames = 0;
  MC.index = 0;
  MC.home = null;
  MC.baseName = "";
  MC.volume = null;
  MC.isoShape = null;
  MC.volumeGroups = null;
  closeMolDensityPanels();
  $("molDensityGroup").classList.add("hidden");
  $("molDensitySep").classList.add("hidden");
  setMolPlayerVisible(false);
  if (MC.viewer) {
    try { MC.viewer.clear(); } catch (err) { /* 忽略 */ }
    MC.viewer = null;
  }
  const box = $("molCanvas");
  if (box) box.innerHTML = "";
  $("molView").classList.add("hidden");
  MC = freshMolCtx();
  activeMask = null;
  if (!anyViewerOpen() && state.viewing) state.viewing = null;
}

async function openStructure(path, anchor) {
  const mask = acquireMask("molView", "view:" + path);
  mask.dataset.dockTag = "3D";
  if (typeof $3Dmol === "undefined") {
    toast("3Dmol 资源未加载，无法显示结构", true, anchor);
    return;
  }
  if (!hasWebGL()) {
    toast("当前浏览器不支持 WebGL，无法显示 3D 结构", true, anchor);
    return;
  }
  try {
    const host = $("molCanvas");
    const data = await api("/api/structure?path=" + q(path) + "&frames=1");
    state.viewing = path;
    MC.sourcePath = path;
    const many = (data.nframes || 1) > 1;
    $("molName").textContent = data.name + " · " + data.formula + " · " + fmtSize(data.size) + " · " + data.mtime;
    stopMolPlay();
    MC.frames = many ? data.nframes : 0;
    MC.index = 0;
    MC.cell = data.cell || null;
    MC.atomStyles = {};
    MC.archive = null;
    molClearMeasure(true);
    molHidePickPanel();
    $("molView").classList.remove("hidden");
    if (MC.viewer) {
      try { MC.viewer.clear(); } catch (err) { /* 忽略 */ }
      MC.viewer = null;
    }
    host.innerHTML = "";
    await new Promise(function (resolve) { requestAnimationFrame(resolve); });
    // upscale:false：让画布后备像素 = CSS 尺寸 × 真实 devicePixelRatio，
    // 与屏幕物理像素 1:1 对应；3Dmol 默认的 upscale 会强制按 2 倍渲染，
    // 在 125%/150% 缩放屏上被非整数缩小，边缘会发虚。
    MC.viewer = $3Dmol.createViewer($("molCanvas"),
      { backgroundAlpha: 0, antialias: true, upscale: false, orthographic: true });
    // 视图变化（拖拽/按钮旋转/复位）时同步重画左下角坐标轴指示器。
    if (MC.viewer.setViewChangeCallback) {
      MC.viewer.setViewChangeCallback(function () { molDrawAxisGizmo(); });
    }
    // 深度雾强度由“样式设置”弹窗控制（0 关闭，1 最强）
    molApplyDepthCue();
    molSetProjection(true);
    if (many) {
      // 多帧轨迹：把全部帧放进同一个 model，setFrame 才能逐帧切换
      MC.viewer.addModelsAsFrames(data.xyz, "xyz");
      molApplyDefaultAtomStyle();
      if (data.cell) MC.cellShapes = drawMolCell(data.cell);
      MC.viewer.setFrame(0);
      $("molRange").max = String(MC.frames - 1);
      setMolPlayerVisible(true);
      molLabel();
    } else {
      const model = MC.viewer.addModel(data.cif, "cif");
      MC.structureModel = model;
      molApplyDefaultAtomStyle();
      if (data.cell) MC.cellShapes = drawMolCell(data.cell);
      setMolPlayerVisible(false);
    }
    // 沿用用户设定的键粗（键型固定为原生 stick）
    molApplyBondRadius();
    MC.viewer.zoomTo();
    MC.viewer.setClickable({}, true, molOnAtomClick);
    configureMolDensity(data);
    // 记录“未应用任何存档”的初始相机，供“重置”回到无 json 的初始状态。
    // 必须在读取 _mcta.json 之前捕获，否则 home 会变成存档里的视图。
    MC.home = {
      view: MC.viewer.getView(),
      look: MC.viewer.lookingAt ? MC.viewer.lookingAt.clone() : null
    };
    MC.baseName = data.name || "structure";
    // 打开结构时先看同目录有无 <文件名>_mcta.json 存档；有则恢复其中记录的操作。
    const arc = await molLoadArchive(molArchivePath(path));
    if (arc) {
      MC.archive = arc;
      molApplyArchive(arc);
    } else {
      MC.viewer.render();
      molDrawAxisGizmo();
    }
    // 加载阶段的样式/投影调用不算“视图调整”；此处开始记录用户改动。
    MC.viewDirtyArmed = true;
    if (!host._mctaViewDirty) {
      host._mctaViewDirty = true;
      host.addEventListener("pointerdown", function (ev) {
        if (ev.button !== 0) return;
        if (ev.target && ev.target.closest && ev.target.closest(".mol-axis-gizmo")) return;
        molMarkViewDirty();  // 左键拖动旋转
      }, true);
    }
    // 滚轮方向与 3Dmol 默认相反：向前滚缩小、向后滚放大。
    // 在容器上以捕获阶段拦截并阻止冒泡，屏蔽 3Dmol 绑定在画布上的滚轮处理。
    if (!host._mctaWheel) {
      host._mctaWheel = true;
      host.addEventListener("wheel", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (!MC.viewer) { return; }
        const cam = MC.viewer.rotationGroup.position;
        const span = 0.85 * (MC.viewer.CAMERA_Z - cam.z);
        const tick = Math.min(Math.abs(ev.deltaY) || 100, 300);
        cam.z += (ev.deltaY < 0 ? 1 : -1) * span * tick / 400;
        cam.z = MC.viewer.adjustZoomToLimits(cam.z);
        MC.viewer.show();
        molMarkViewDirty();
      }, { passive: false, capture: true });
    }
    // 右键：命中原子打开原子样式，空白处打开样式设置；屏蔽浏览器默认菜单。
    if (!host._mctaContextMenu) {
      host._mctaContextMenu = true;
      host.addEventListener("contextmenu", molOnContextMenu);
    }
  } catch (err) {
    toast(err.message, true, anchor);
    closeStructure();
  }
}

function b64encode(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  bytes.forEach(function (b) { binary += String.fromCharCode(b); });
  return btoa(binary);
}

function b64decode(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) { bytes[i] = binary.charCodeAt(i); }
  return bytes;
}

function termSize() {
  const box = $("termBox");
  const cols = Math.max(20, Math.floor((box.clientWidth - 24) / 8.2));
  const rows = Math.max(10, Math.floor((box.clientHeight - 24) / 17));
  return {cols: cols, rows: rows};
}

function relFromBase(cwd, base) {
  if (!cwd || !base) return null;
  if (cwd === base) return "";
  const prefix = base.charAt(base.length - 1) === "/" ? base : base + "/";
  if (cwd.indexOf(prefix) !== 0) return null;
  return cwd.slice(prefix.length);
}

async function syncCwd() {
  if (!state.term) return;
  try {
    const data = await api("/api/term/cwd");
    if (!data.cwd || data.cwd === state.lastCwd) return;
    state.lastCwd = data.cwd;
    // 终端可以进入任意目录（如 /mnt/d）；服务端按终端 cwd 放行。
    if (data.cwd !== state.cwd) await load(data.cwd, true);
  } catch (err) { /* 忽略路径同步错误 */ }
}

// 把路径输入框的内容变成真实目录：先让终端 cd（保持页面与终端同步），
// 再交给 syncCwd 刷新列表；终端不可用时直接请求。
function sendTermInput(text) {
  if (!state.term) return Promise.reject(new Error("终端未连接"));
  return api("/api/term/input", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({data: b64encode(text), sid: SESSION_ID})
  });
}

// 页面切换目录前，先清掉终端里已输入但尚未回车的内容。
// Ctrl+E 跳到行尾、Ctrl+U 清掉整行；与 cd 同批发送，避免清行后被当成新输入残留。
function sendTermCd(target) {
  const quoted = "'" + String(target).replace(/'/g, "'\\\\''") + "'";
  return sendTermInput("\\u0005\\u0015cd " + quoted + "\\n");
}

// 规整为绝对路径：相对输入基于当前显示的目录，去掉多余的 /、.、..。
function absNormPath(raw, base) {
  let p = String(raw || "").trim().replace(/\\\\/g, "/");
  if (!p) return "";
  if (p.charAt(0) !== "/") p = (base || "/").replace(/\\/+$/, "") + "/" + p;
  const segs = [];
  p.split("/").forEach(function (s) {
    if (!s || s === ".") return;
    if (s === "..") { segs.pop(); return; }
    segs.push(s);
  });
  return "/" + segs.join("/");
}

// 点击“进入”或回车：空输入或与当前目录一致则不动作；否则让终端 cd，
// 由 syncCwd 跟随刷新。无效路径 cd 会失败，cwd 不变，页面自然不切换。
function navigateToPath(raw) {
  const el = $("pathNote");
  const old = el ? (el.dataset.label || "") : "";
  const base = absNormPath(old || state.cwd, "/");
  const target = absNormPath(raw, base);
  if (!target || target === base) {
    if (el) el.value = old;
    return false;
  }
  // 先还原输入框：有效路径会在 cwd 跟随刷新时更新为新的目录，
  // 无效路径则 cd 失败、cwd 不变，输入框保持当前路径（点击无效）。
  if (el) el.value = old;
  sendTermCd(target).catch(function () { load(target, true); });
  return true;
}

(function initPathInput() {
  const el = $("pathNote");
  const btn = $("pathGo");
  if (!el) return;
  function restore() { el.value = el.dataset.label || ""; }
  function submit() { navigateToPath(el.value); }
  el.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") {
      ev.preventDefault();
      submit();
      this.blur();
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      restore();
      this.blur();
    }
  });
  el.addEventListener("blur", restore);
  if (btn) {
    // 阻止按钮抢焦点，避免 blur 先把输入还原成旧路径。
    btn.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
    btn.addEventListener("click", submit);
  }
})();

/* ---- 侧栏终端字符雨特效 ---- */
(function () {
  const box = $("termBox");
  const canvas = $("termRain");
  if (!box || !canvas) return;
  const ctx = canvas.getContext("2d");
  let raf = null, active = false, visible = true, last = 0, step = null;
  let paused = false, resizeTimer = null, lastTick = 0;

  function setup() {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const chars = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン0123456789=<>+-*/|\\#@$%&";
    const fontSize = 13;
    const cols = Math.floor(w / fontSize);
    const drops = new Array(cols).fill(1).map(() => Math.random() * -20);
    return function () {
      ctx.fillStyle = "rgba(16, 21, 29, 0.09)";
      ctx.fillRect(0, 0, w, h);
      ctx.font = fontSize + "px ui-monospace, Menlo, Consolas, monospace";
      for (let i = 0; i < cols; i++) {
        const ch = chars[Math.floor(Math.random() * chars.length)];
        ctx.fillStyle = "rgba(126, 231, 135, 0.85)";
        ctx.fillText(ch, i * fontSize, drops[i] * fontSize);
        if (drops[i] * fontSize > h && Math.random() > 0.975) drops[i] = 0;
        drops[i]++;
      }
    };
  }

  function isRainCovered() {
    const r = box.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return true;
    const x = Math.min(window.innerWidth - 1, Math.max(0, r.left + r.width / 2));
    const y = Math.min(window.innerHeight - 1, Math.max(0, r.top + r.height / 2));
    const top = document.elementFromPoint(x, y);
    // LICENSE 浮层只是覆盖显示，不视为遮挡终端，字符雨继续运行。
    if (top && top.closest && top.closest("#licenseOverlay")) return false;
    return !!top && !box.contains(top);
  }

  function canRun() {
    // 字符雨只在侧栏终端显示；浮窗（含最小化停靠）不呈现。
    const wrap = box.closest(".term-wrap");
    if (wrap && wrap.classList.contains("floating")) return false;
    return !paused && !document.hidden && visible && !isRainCovered();
  }

  function frame(ts) {
    if (!active) return;
    if (!last || ts - last >= 60) {
      last = ts;
      try { step(); lastTick = Date.now(); }
      catch (err) { stop(); lastTick = 0; } // 绘制异常交给看门狗重建
    }
    raf = requestAnimationFrame(frame);
  }

  function start() {
    if (active || !canRun()) return;
    let next;
    try { next = setup(); } catch (err) { return; }
    step = next;
    active = true;
    canvas.style.opacity = "";
    last = 0;
    lastTick = Date.now();
    raf = requestAnimationFrame(frame);
  }

  function stop() {
    active = false;
    canvas.style.opacity = "0";
    if (raf) { cancelAnimationFrame(raf); raf = null; }
  }

  // 卡死自恢复：RAF 停摆、绘制抛错、暂停标记残留时强制重建。
  function kick() {
    stop();
    lastTick = 0;
    start();
  }
  setInterval(function () {
    const now = Date.now();
    if (!canRun()) {
      if (paused && !resizeTimer) paused = false; // 暂停定时器丢失时解除卡住的暂停
      return;
    }
    if (!active || !lastTick || now - lastTick > 1500) kick();
  }, 1000);

  function syncRain() { if (canRun()) start(); else stop(); }
  ["pointerdown", "click", "scroll"].forEach(function (evt) {
    document.addEventListener(evt, function () { setTimeout(syncRain, 0); }, true);
  });
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop(); else start();
  });
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      visible = entries[0].isIntersecting;
      if (visible) start(); else stop();
    }, { threshold: 0.01 }).observe(box);
  }
  // 统一暂停入口：模式切换、浮窗缩放、页面缩放、终端交互都走这里；结束后按当前终端尺寸重建。
  function pauseRain(ms) {
    const wait = typeof ms === "number" && ms > 0 ? ms : 180;
    paused = true;
    stop();
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      resizeTimer = null;
      paused = false;
      start();
    }, wait);
  }
  function pauseRainForResize() { pauseRain(180); }
  window.addEventListener("resize", pauseRainForResize);
  if ("ResizeObserver" in window) {
    let roFirst = true;
    new ResizeObserver(function () {
      if (roFirst) { roFirst = false; return; }
      pauseRainForResize();
    }).observe(box);
  }
  // 鼠标选择、键盘输入期间暂停字符雨，停止操作后自动恢复。
  box.addEventListener("pointerdown", function () { pauseRain(500); }, true);
  box.addEventListener("pointermove", function (e) { if (e.buttons) pauseRain(500); }, true);
  box.addEventListener("pointerup", function () { pauseRain(500); }, true);
  box.addEventListener("keydown", function () { pauseRain(500); }, true);
  box.addEventListener("input", function () { pauseRain(500); }, true);
  start();
  window.__mctaRainPause = function (ms) { pauseRain(ms); };
  window.__mctaRainResize = function () { pauseRain(180); };
  window.__mctaRainKick = kick;
  window.__mctaRainState = function () {
    return { active: active, paused: paused, lastTick: lastTick, canRun: canRun() };
  };
})();

function legacyCopyText(text) {
  const active = document.activeElement;
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.cssText = "position:fixed;top:-1000px;opacity:0";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
  ta.remove();
  if (active && active.focus) {
    try { active.focus(); } catch (err) { /* 忽略 */ }
  }
  return ok;
}

function fitTerm() {
  if (!state.term) return;
  const next = termSize();
  state.term.resize(next.cols, next.rows);
}

function startTerminal() {
  if (state.term || !state.user || !window.Terminal) return;
  $("termHint").classList.add("hidden");
  const size = termSize();
  const term = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    fontFamily: 'ui-monospace, Consolas, "Courier New", monospace',
    theme: {background: "#10151d", foreground: "#d7deea", cursor: "#7fa8ff", selectionBackground: "#2a3b57"}
  });
  term.open($("termBox"));
  term.resize(size.cols, size.rows);
  state.term = term;

  const termBox = $("termBox");
  termBox.addEventListener("mouseup", function () {
    setTimeout(function () {
      const text = state.term ? state.term.getSelection() : "";
      if (!text) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          toast("已复制选中文字");
        }, function () {
          if (legacyCopyText(text)) {
            toast("已复制选中文字");
            if (state.term) state.term.focus();
          }
        });
      } else if (legacyCopyText(text)) {
        toast("已复制选中文字");
        if (state.term) state.term.focus();
      }
    }, 0);
  });
  termBox.addEventListener("contextmenu", function (e) {
    e.preventDefault();
    if (!(navigator.clipboard && navigator.clipboard.readText)) {
      toast("无法读取剪切板", true);
      return;
    }
    navigator.clipboard.readText().then(function (text) {
      if (!text) { toast("剪切板为空"); return; }
      if (state.term.paste) state.term.paste(text);
      else state.term.write(text);
      toast("已粘贴剪切板内容");
    }, function () {
      toast("无法读取剪切板", true);
    });
  }, true);

  let cwdKick = null;
  term.onData(function (data) {
    api("/api/term/input", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({data: b64encode(data), sid: SESSION_ID})
    }).catch(function (err) { toast(err.message, true); });
    if (data.indexOf("\\r") >= 0 || data.indexOf("\\n") >= 0) {
      clearTimeout(cwdKick);
      cwdKick = setTimeout(syncCwd, 200);
    }
  });

  term.onResize(function (ev) {
    api("/api/term/resize", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({cols: ev.cols, rows: ev.rows, sid: SESSION_ID})
    }).catch(function () { /* 忽略 */ });
  });

  const es = new EventSource("/api/term/stream?cols=" + size.cols + "&rows=" + size.rows + "&sid=" + q(SESSION_ID));
  state.es = es;
  es.onmessage = function (event) {
    if (!event.data) return;
    term.write(b64decode(event.data));
  };
  es.onerror = function () {
    $("termState").textContent = tx("连接中断，正在重试…") + " · " + state.user;
  };
  es.onopen = function () {
    $("termState").textContent = tx("已连接") + " · " + state.user;
  };

  state.cwdTimer = setInterval(syncCwd, 400);
  syncCwd();

  window.addEventListener("resize", function () {
    if (!state.term) return;
    fitTerm();
  });
}

/* ---- 终端浮窗：点击终端顶端栏浮起，可拖动、缩放、停靠、最小化 ---- */
(function initTermFloat() {
  const box = $("termBox");
  const wrap = box ? box.closest(".term-wrap") : null;
  if (!wrap) return;
  const head = wrap.querySelector(".term-head");
  const tools = wrap.querySelector(".term-tools");
  const handles = wrap.querySelectorAll(".resize-handle");
  const dockParent = wrap.parentNode;
  const dockNext = wrap.nextSibling;
  const UI_KEY = "mcta-term-ui";
  let uiMode = "dock";        // 'dock' | 'float'
  let maximized = false;
  let minimized = false;
  let prevRect = null;
  let drag = null;
  let resize = null;
  let uiState = {};

  try { uiState = JSON.parse(localStorage.getItem(UI_KEY) || "{}") || {}; }
  catch (e) { uiState = {}; }

  function saveUI(patch) {
    Object.keys(patch).forEach(function (k) { uiState[k] = patch[k]; });
    try { localStorage.setItem(UI_KEY, JSON.stringify(uiState)); } catch (e) { /* 忽略 */ }
  }

  function currentRect() {
    const r = wrap.getBoundingClientRect();
    return { x: r.left, y: r.top, w: r.width, h: r.height };
  }

  function clampRect(r) {
    const maxW = Math.max(260, window.innerWidth - 16);
    const maxH = Math.max(170, window.innerHeight - 16);
    r.w = Math.min(Math.max(260, r.w || 520), maxW);
    r.h = Math.min(Math.max(170, r.h || 380), maxH);
    // 约束顶栏边沿的中心点：顶栏上边沿中心 (x+w/2, y) 与下边沿中心 (x+w/2, y+HEAD)
    // 都必须留在页面内。水平按中心点，垂直上边沿>=0、下边沿<=innerHeight。
    const HEAD = 44;
    r.x = Math.min(Math.max(-r.w / 2, r.x || 0), window.innerWidth - r.w / 2);
    r.y = Math.min(Math.max(0, r.y || 0), Math.max(0, window.innerHeight - HEAD));
    return r;
  }

  function applyRect(r) {
    wrap.style.left = Math.round(r.x) + "px";
    wrap.style.top = Math.round(r.y) + "px";
    wrap.style.width = Math.round(r.w) + "px";
    wrap.style.height = Math.round(r.h) + "px";
  }

  function maxRect() {
    return { x: 8, y: 8, w: window.innerWidth - 16, h: window.innerHeight - 16 };
  }

  function defaultRect() {
    const w = Math.min(560, Math.max(300, window.innerWidth - 32));
    const h = Math.min(420, Math.max(240, window.innerHeight - 120));
    return clampRect({ x: 20, y: window.innerHeight - h - 20, w: w, h: h });
  }

  function floatAt(rect) {
    if (uiMode !== "float") {
      document.body.appendChild(wrap);
      wrap.classList.add("floating");
      uiMode = "float";
    }
    wrap.classList.remove("win-min");
    minDockRemove(wrap);
    layoutMinDock(); // 终端离开停靠栏后，其余图标自动左移补位
    bringFloatToFront(wrap);
    applyRect(clampRect({ x: rect.x, y: rect.y, w: rect.w, h: rect.h }));
    maximized = false;
    minimized = false;
    prevRect = null;
    showHandles(true);
    syncTools();
    scheduleFit();
  }

  function dock() {
    if (uiMode !== "float") return;
    wrap.classList.remove("floating", "win-min");
    minDockRemove(wrap);
    layoutMinDock(); // 终端离开停靠栏后，其余图标自动补位
    wrap.style.left = wrap.style.top = wrap.style.width = wrap.style.height = "";
    wrap.style.zIndex = "";
    showHandles(false);
    dockParent.insertBefore(wrap, dockNext && dockNext.parentNode === dockParent ? dockNext : null);
    uiMode = "dock";
    maximized = false;
    minimized = false;
    prevRect = null;
    saveUI({ mode: "dock", x: null, y: null, w: null, h: null, max: false, restore: null });
    syncTools();
    scheduleFit();
  }

  function minimizeWin() {
    if (uiMode !== "float" || minimized) return;
    // 最小化前记录当前几何，供还原时恢复；最大化态先还原到之前的尺寸再记录。
    let r = currentRect();
    if (maximized && prevRect) {
      applyRect(prevRect);
      r = currentRect();
    }
    minimized = true;
    maximized = false;
    prevRect = null;
    wrap.classList.add("win-min");
    showHandles(false);
    minDockAdd(wrap);
    bringFloatToFront(wrap);
    layoutMinDock();
    saveUI({ mode: "float", min: true, x: r.x, y: r.y, w: r.w, h: r.h, max: false, restore: null });
    syncTools();
    scheduleFit();
  }

  function restoreWin() {
    if (uiMode !== "float") { floatAt(uiState.w ? uiState : defaultRect()); return; }
    if (!minimized) { resetToDefault(); return; }
    minimized = false;
    wrap.classList.remove("win-min");
    minDockRemove(wrap);
    const saved = (typeof uiState.w === "number" && uiState.w > 0)
      ? { x: uiState.x, y: uiState.y, w: uiState.w, h: uiState.h } : null;
    floatAt(saved || defaultRect());
    saveUI({ min: false });
    layoutMinDock();
  }

  function resetToDefault() {
    floatAt(defaultRect());
  }

  function scheduleFit() {
    // 侧栏/浮窗切换、最小化还原、浮窗缩放结束后都要按新尺寸重建字符雨。
    if (window.__mctaRainPause) window.__mctaRainPause(180);
    requestAnimationFrame(function () {
      fitTerm();
      if (window.__mctaRainResize) window.__mctaRainResize();
    });
  }

  function syncTools() {
    if (tools) {
      const labels = {
        min: tx("最小化"),
        restore: tx("还原"),
        max: maximized ? tx("缩回原始大小") : tx("放大到整个页面"),
        dock: tx("还原到侧栏")
      };
      tools.querySelectorAll("button[data-term-act]").forEach(function (b) {
        const label = labels[b.getAttribute("data-term-act")];
        if (!label) return;
        b.title = label;
        b.setAttribute("aria-label", label);
      });
      // 最大化按钮与文件浮窗同款：⬀/⬃ 双图标切换
      const maxBtn = tools.querySelector('button[data-term-act="max"]');
      if (maxBtn) setModalMaxButton(maxBtn, maximized);
    }
    // 提示只挂在终端顶栏：悬停终端内部不再出现“点击终端顶端栏可浮动为小窗口”。
    if (wrap) wrap.title = "";
    if (head) head.title = uiMode === "float" ? "" : tx("点击终端顶端栏可浮动为小窗口");
  }

  function showHandles(show) {
    const display = show ? "block" : "none";
    handles.forEach(function (h) { h.style.display = display; });
  }

  function persistRect() {
    if (uiMode !== "float" || minimized) return;
    const r = currentRect();
    saveUI({
      mode: "float", min: false, x: r.x, y: r.y, w: r.w, h: r.h,
      max: maximized, restore: maximized ? prevRect : null
    });
  }

  function toggleMax() {
    if (uiMode !== "float") return;
    if (minimized) restoreWin();
    if (maximized) {
      maximized = false;
      if (prevRect) applyRect(clampRect(prevRect));
      prevRect = null;
    } else {
      prevRect = currentRect();
      maximized = true;
      applyRect(maxRect());
    }
    persistRect();
    syncTools();
    scheduleFit();
  }

  if (tools) {
    tools.addEventListener("click", function (e) {
      const btn = e.target.closest("button[data-term-act]");
      if (!btn) return;
      e.stopPropagation();
      const act = btn.getAttribute("data-term-act");
      if (act === "dock") { if (uiMode === "float") dock(); return; }
      if (uiMode !== "float") floatAt(uiState.w ? uiState : defaultRect());
      if (act === "max") { toggleMax(); return; }
      if (act === "min") { minimizeWin(); return; }
      if (act === "restore") { restoreWin(); return; }
    });
  }

  if (head) {
    head.addEventListener("pointerdown", function (e) {
      if (e.target.closest("button") || minimized) return;
      if (uiMode !== "float") floatAt(uiState.w ? uiState : defaultRect());
      const r = currentRect();
      drag = { dx: e.clientX - r.x, dy: e.clientY - r.y, w: r.w, h: r.h, id: e.pointerId };
      try { head.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
      wrap.classList.add("dragging");
    });
    head.addEventListener("pointermove", function (e) {
      if (!drag) return;
      e.preventDefault();
      const r = clampRect({
        x: e.clientX - drag.dx, y: e.clientY - drag.dy, w: drag.w, h: drag.h
      });
      wrap.style.left = Math.round(r.x) + "px";
      wrap.style.top = Math.round(r.y) + "px";
      maximized = false;
    });
    const endDrag = function () {
      if (!drag) return;
      try { head.releasePointerCapture(drag.id); } catch (err) { /* 忽略 */ }
      drag = null;
      wrap.classList.remove("dragging");
      persistRect();
      syncTools();
    };
    head.addEventListener("pointerup", endDrag);
    head.addEventListener("pointercancel", endDrag);
    // 最小化态点击顶栏文字还原（跳过按钮）
    head.addEventListener("click", function (e) {
      if (!minimized || e.target.closest("button")) return;
      e.stopPropagation();
      restoreWin();
    });
  }

  handles.forEach(function (h) {
    h.addEventListener("pointerdown", function (e) {
      e.stopPropagation();
      if (window.__mctaRainPause) window.__mctaRainPause(300);
      maximized = false; prevRect = null;
      const r = currentRect();
      const cls = h.className;
      let sx = e.clientX, sy = e.clientY;
      resize = {
        startX: sx, startY: sy,
        x: r.x, y: r.y, w: r.w, h: r.h,
        edgeT: cls.indexOf("rh-t") >= 0 && cls.indexOf("rh-tr") < 0 && cls.indexOf("rh-tl") < 0,
        edgeB: cls.indexOf("rh-b") >= 0 && cls.indexOf("rh-br") < 0 && cls.indexOf("rh-bl") < 0,
        edgeL: cls.indexOf("rh-l") >= 0 && cls.indexOf("rh-tl") < 0 && cls.indexOf("rh-bl") < 0,
        edgeR: cls.indexOf("rh-r") >= 0 && cls.indexOf("rh-tr") < 0 && cls.indexOf("rh-br") < 0,
        cornerTL: cls.indexOf("rh-tl") >= 0,
        cornerTR: cls.indexOf("rh-tr") >= 0,
        cornerBL: cls.indexOf("rh-bl") >= 0,
        cornerBR: cls.indexOf("rh-br") >= 0,
        id: e.pointerId
      };
      try { h.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
      wrap.classList.add("dragging");
    });
    h.addEventListener("pointermove", function (e) {
      if (!resize) return;
      e.preventDefault();
      if (window.__mctaRainPause) window.__mctaRainPause(300);
      const dx = e.clientX - resize.startX;
      const dy = e.clientY - resize.startY;
      let x = resize.x, y = resize.y, w = resize.w, h = resize.h;
      if (resize.edgeR || resize.cornerTR || resize.cornerBR) w = resize.w + dx;
      if (resize.edgeL || resize.cornerTL || resize.cornerBL) { w = resize.w - dx; x = resize.x + dx; }
      if (resize.edgeB || resize.cornerBL || resize.cornerBR) h = resize.h + dy;
      if (resize.edgeT || resize.cornerTL || resize.cornerTR) { h = resize.h - dy; y = resize.y + dy; }
      const r = clampRect({ x: x, y: y, w: w, h: h });
      wrap.style.left = Math.round(r.x) + "px";
      wrap.style.top = Math.round(r.y) + "px";
      wrap.style.width = Math.round(r.w) + "px";
      wrap.style.height = Math.round(r.h) + "px";
    });
    const endResize = function () {
      if (!resize) return;
      try { h.releasePointerCapture(resize.id); } catch (err) { /* 忽略 */ }
      resize = null;
      wrap.classList.remove("dragging");
      persistRect();
      scheduleFit();
    };
    h.addEventListener("pointerup", endResize);
    h.addEventListener("pointercancel", endResize);
  });

  window.addEventListener("resize", function () {
    if (uiMode !== "float") return;
    if (maximized) applyRect(maxRect());
    else applyRect(clampRect(currentRect()));
    scheduleFit();
  });

  syncTools();
  if (uiState.mode === "float") {
    const saved = {
      x: typeof uiState.x === "number" ? uiState.x : window.innerWidth - 580,
      y: typeof uiState.y === "number" ? uiState.y : window.innerHeight - 460,
      w: uiState.w || 560,
      h: uiState.h || 420
    };
    if (uiState.min) {
      // 上次停靠在最小化栏：浮起后立即转为最小化并重新加入停靠栏。
      floatAt(saved);
      minimizeWin();
    } else {
      floatAt(saved);
      if (uiState.max) {
        maximized = true;
        prevRect = uiState.restore || null;
        applyRect(maxRect());
        syncTools();
        scheduleFit();
      }
    }
  }
})();

function applyInfo(info) {
  state.user = info.user;
  state.root = info.root;
  $("rootPath").textContent = info.root;
  $("rootLabel").textContent = tx("运行目录");
  $("authText").textContent = info.user;
  $("termState").textContent = tx("连接中…") + " · " + info.user;
}

// 弹窗最大化：占满整个页面，再点一次回到原始大小
function setModalMaxButton(btn, on) {
  const maxIcon = btn.querySelector(".max-icon");
  const restoreIcon = btn.querySelector(".restore-icon");
  if (maxIcon && restoreIcon) {
    maxIcon.classList.toggle("hidden", on);
    restoreIcon.classList.toggle("hidden", !on);
  } else {
    btn.textContent = on ? tx("还原") : tx("放大");
  }
  const title = on ? tx("缩回原始大小") : tx("放大到整个页面");
  btn.title = title;
  btn.setAttribute("aria-label", title);
}

function resetModalMax(mask) {
  mask.classList.remove("maxed");
  const btn = mask.querySelector(".max-btn");
  if (btn) setModalMaxButton(btn, false);
}

Array.prototype.forEach.call(document.querySelectorAll(".max-btn"), function (btn) {
  btn.onclick = function () {
    const mask = this.closest(".mol-mask");
    const win = mask.querySelector(".mol-win");
    // 最小化态下先还原窗口，再执行最大化
    if (win && win.classList.contains("win-min")) {
      win.classList.remove("win-min");
      minDockRemove(win);
      const saved = mask.dataset.minRect;
      if (saved) { try { const o = JSON.parse(saved); mask._applyFree(o); } catch (e) {} }
      delete mask.dataset.minRect;
      restoreDockTitle(mask);
      layoutMinDock();
    }
    const on = !mask.classList.contains("maxed");
    mask.classList.toggle("maxed", on);
    setModalMaxButton(this, on);
    if (mask.dataset.baseId === "molView" && MC.viewer) {
      requestAnimationFrame(function () { MC.viewer.resize(); MC.viewer.render(); });
    }
  };
});

/* ---- 弹窗浮动：拖动标题栏、右下角调整大小、还原到初始状态 ---- */
function initModalFloating(mask) {
  const MIN_W = 320;
  const MIN_H = 200;
  function winOf(mask) { return mask.querySelector(".mol-win"); }

  function ensureHandle(mask) {
    const win = winOf(mask);
    if (!win) return;
    ["t", "b", "l", "r", "tl", "tr", "bl", "br"].forEach(function (part) {
      if (!win.querySelector(".mol-rh-" + part)) {
        const h = document.createElement("span");
        h.className = "mol-rh mol-rh-" + part;
        h.setAttribute("aria-hidden", "true");
        h.dataset.corner = part;
        win.appendChild(h);
      }
    });
  }

  function snapshot(mask) {
    // 记录初始位置/尺寸：以未拖动状态下浏览器布局为准
    const win = winOf(mask);
    if (!win) return null;
    if (mask.dataset.initRect) {
      try { return JSON.parse(mask.dataset.initRect); } catch (e) { /* 忽略 */ }
    }
    // 计算 mask 的 flex 居中位置
    const wasFree = win.classList.contains("free");
    const saved = wasFree ? {
      left: win.style.left, top: win.style.top,
      width: win.style.width, height: win.style.height
    } : null;
    if (wasFree) {
      win.classList.remove("free");
      win.style.left = win.style.top = win.style.width = win.style.height = "";
    }
    const r = win.getBoundingClientRect();
    const rect = { x: r.left, y: r.top, w: r.width, h: r.height };
    mask.dataset.initRect = JSON.stringify(rect);
    if (wasFree) {
      win.classList.add("free");
      win.style.left = saved.left; win.style.top = saved.top;
      win.style.width = saved.width; win.style.height = saved.height;
    }
    return rect;
  }

  function applyFree(mask, rect) {
    const win = winOf(mask);
    if (!win) return;
    win.classList.add("free");
    win.style.left = Math.round(rect.x) + "px";
    win.style.top = Math.round(rect.y) + "px";
    win.style.width = Math.round(rect.w) + "px";
    win.style.height = Math.round(rect.h) + "px";
    ensureHandle(mask);
  }

  function resetFree(mask) {
    const win = winOf(mask);
    if (!win) return;
    win.classList.remove("free", "win-min");
    minDockRemove(win);
    layoutMinDock(); // 浮窗关闭/隐藏后，其余停靠图标自动补位
    restoreDockTitle(mask);
    win.style.left = win.style.top = win.style.width = win.style.height = "";
    delete mask.dataset.initRect;
    delete mask.dataset.minRect;
    if (mask.dataset.baseId === "molView" && MC.viewer) {
      requestAnimationFrame(function () { try { MC.viewer.resize(); MC.viewer.render(); } catch (e) {} });
    }
  }

  function clampRect(r) {
    r.w = Math.min(Math.max(MIN_W, r.w), window.innerWidth - 16);
    r.h = Math.min(Math.max(MIN_H, r.h), window.innerHeight - 16);
    // 约束顶栏边沿的中心点：上边沿中心 (x+w/2, y)、下边沿中心 (x+w/2, y+HEAD) 留在页面内。
    const HEAD = 40;
    r.x = Math.min(Math.max(-r.w / 2, r.x), window.innerWidth - r.w / 2);
    r.y = Math.min(Math.max(0, r.y), Math.max(0, window.innerHeight - HEAD));
    return r;
  }

  mask._snapshot = function () { return snapshot(mask); };
  mask._applyFree = function (rect) { applyFree(mask, rect); };
  mask._resetFree = function () { resetFree(mask); };
  // 页面尺寸变化时，对已自由定位且非最小化的浮窗重新 clamp，保证顶栏中心点仍在页面内。
  mask._reclamp = function () {
    const win = winOf(mask);
    if (!win || !win.classList.contains("free") || win.classList.contains("win-min")) return;
    if (mask.classList.contains("maxed")) return;
    applyFree(mask, clampRect(snapshot(mask)));
  };

  const head = mask.querySelector(".mol-head");
  const win = winOf(mask);
  if (!head || !win) return;
    ensureHandle(mask);

    // 拖动标题栏
    let drag = null;
    head.addEventListener("pointerdown", function (e) {
      if (mask.classList.contains("maxed") || win.classList.contains("win-min")) return;
      if (e.target.closest("button")) return;
      const rect = win.classList.contains("free")
        ? { x: parseFloat(win.style.left) || 0, y: parseFloat(win.style.top) || 0,
            w: win.getBoundingClientRect().width, h: win.getBoundingClientRect().height }
        : snapshot(mask);
      if (!rect) return;
      drag = { dx: e.clientX - rect.x, dy: e.clientY - rect.y, w: rect.w, h: rect.h, id: e.pointerId };
      applyFree(mask, rect);
      try { head.setPointerCapture(e.pointerId); } catch (err) {}
      e.preventDefault();
    });
    head.addEventListener("pointermove", function (e) {
      if (!drag) return;
      e.preventDefault();
      applyFree(mask, clampRect({
        x: e.clientX - drag.dx, y: e.clientY - drag.dy, w: drag.w, h: drag.h
      }));
    });
    const endDrag = function () {
      if (!drag) return;
      try { head.releasePointerCapture(drag.id); } catch (err) {}
      drag = null;
    };
    head.addEventListener("pointerup", endDrag);
    head.addEventListener("pointercancel", endDrag);

    // 四边/四角 resize
    let resize = null;
    win.querySelectorAll(".mol-rh").forEach(function (handle) {
      handle.addEventListener("pointerdown", function (e) {
        if (mask.classList.contains("maxed") || win.classList.contains("win-min")) return;
        e.stopPropagation();
        const r = win.getBoundingClientRect();
        resize = {
          startX: e.clientX, startY: e.clientY,
          x: r.left, y: r.top, w: r.width, h: r.height,
          corner: handle.dataset.corner, id: e.pointerId
        };
        applyFree(mask, { x: r.left, y: r.top, w: r.width, h: r.height });
        try { handle.setPointerCapture(e.pointerId); } catch (err) {}
        e.preventDefault();
      });
      handle.addEventListener("pointermove", function (e) {
        if (!resize) return;
        e.preventDefault();
        const dx = e.clientX - resize.startX;
        const dy = e.clientY - resize.startY;
        let x = resize.x, y = resize.y, w = resize.w, h = resize.h;
        const c = resize.corner;
        if (c === "br" || c === "tr" || c === "r") w = resize.w + dx;
        else if (c === "bl" || c === "tl" || c === "l") { w = resize.w - dx; x = resize.x + dx; }
        if (c === "br" || c === "bl" || c === "b") h = resize.h + dy;
        else if (c === "tr" || c === "tl" || c === "t") { h = resize.h - dy; y = resize.y + dy; }
        applyFree(mask, clampRect({ x: x, y: y, w: w, h: h }));
      });
      const endResize = function () {
        if (!resize) return;
        try { handle.releasePointerCapture(resize.id); } catch (err) {}
        resize = null;
        if (mask.dataset.baseId === "molView" && MC.viewer) {
          requestAnimationFrame(function () { try { MC.viewer.resize(); MC.viewer.render(); } catch (e) {} });
        }
      };
      handle.addEventListener("pointerup", endResize);
      handle.addEventListener("pointercancel", endResize);
    });

    // 最小化态点击顶栏标题文字还原（跳过按钮）
    head.addEventListener("click", function (e) {
      const win0 = winOf(mask);
      if (!win0 || !win0.classList.contains("win-min")) return;
      if (e.target.closest("button")) return;
      if (e.target.closest("h2")) { e.stopPropagation(); restoreBtn.click(); }
    });

    // 最小化：主体隐藏、只留顶栏，停靠页面下方
    const minBtn = mask.querySelector(".min-btn");
    if (minBtn) {
      minBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        const win = winOf(mask);
        if (!win || win.classList.contains("win-min")) return;
        // 记录当前几何，供还原恢复；最大化态先退回之前的尺寸。
        let r;
        if (mask.classList.contains("maxed")) {
          resetModalMax(mask);
          const saved = mask.dataset.minRect;
          if (saved) {
            try { const o = JSON.parse(saved); applyFree(mask, o); } catch (err) {}
          }
        }
        r = win.getBoundingClientRect();
        mask.dataset.minRect = JSON.stringify({ x: r.left, y: r.top, w: r.width, h: r.height });
        // 停靠栏只显示文件名：保存完整标题，再精简为纯文件名
        const h2 = head.querySelector("h2");
        if (h2) {
          if (mask.dataset.fullTitle === undefined) mask.dataset.fullTitle = h2.textContent;
          const name = dockFileName(mask, h2);
          const tag = String(mask.dataset.dockTag || "");
          h2.dataset.dockName = tag ? name + " · " + tag : name;
          h2.textContent = name;
        }
        win.classList.add("win-min");
        minDockAdd(win);
        bringFloatToFront(mask);
        layoutMinDock();
        if (mask.dataset.baseId === "molView" && MC.viewer) {
          requestAnimationFrame(function () { try { MC.viewer.resize(); MC.viewer.render(); } catch (e) {} });
        }
      });
    }

    // 还原：最小化时回到最小化前位置/尺寸；否则归位弹窗
    const restoreBtn = mask.querySelector(".restore-btn");
    if (restoreBtn) {
      restoreBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        const win = winOf(mask);
        if (win && win.classList.contains("win-min")) {
          win.classList.remove("win-min");
          minDockRemove(win);
          const saved = mask.dataset.minRect;
          if (saved) {
            try { const o = JSON.parse(saved); applyFree(mask, o); } catch (err) {}
          }
          delete mask.dataset.minRect;
          const h2 = head.querySelector("h2");
          if (h2 && mask.dataset.fullTitle !== undefined) {
            h2.textContent = mask.dataset.fullTitle;
            delete mask.dataset.fullTitle;
          }
          if (h2) delete h2.dataset.dockName;
          bringFloatToFront(mask);
          layoutMinDock();
        } else {
          resetModalMax(mask);
          resetFree(mask);
        }
        if (mask.dataset.baseId === "molView" && MC.viewer) {
          requestAnimationFrame(function () { try { MC.viewer.resize(); MC.viewer.render(); } catch (e) {} });
        }
      });
    }
}

// 弹窗每次隐藏时清除 free 状态，回到初始居中
const modalObserver = new MutationObserver(function (muts) {
  muts.forEach(function (m) {
    const mask = m.target;
    if (!(mask instanceof HTMLElement)) return;
    if (mask.classList.contains("hidden") && typeof mask._resetFree === "function") mask._resetFree();
  });
});
function observeModal(mask) {
  modalObserver.observe(mask, { attributes: true, attributeFilter: ["class"] });
}
["molView", "quickView"].forEach(function (id) {
  const mask = document.getElementById(id);
  if (mask) { initModalFloating(mask); observeModal(mask); }
});

$("btnMolClose").onclick = closeStructureWithConfirm;
$("molProj").onclick = function () { molSetProjection(!MC.ortho); };
// ↑ 下载按钮：将当前结构文件下载到电脑；保存图片到电脑是左侧独立按钮。
$("molSave").onclick = function () {
  const p = MC.sourcePath || state.viewing || "";
  if (p) downloadFile(p);
  else toast(tx("尚未打开结构"), true, this);
};
$("molSaveImage").onclick = openMolSave;
$("molArchive").onclick = function () { molSaveArchive(this); };
$("molSaveOk").onclick = confirmMolSave;
$("molSaveCancel").onclick = closeMolSave;
$("molFormat").onchange = syncMolSaveName;
$("molScale").onchange = syncMolSaveName;
$("molSaveName").onkeydown = function (ev) {
  if (ev.key === "Enter") { ev.preventDefault(); confirmMolSave(); }
  else if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); closeMolSave(); }
};
$("molRotL").onclick = function () { molRotate(-1); };
$("molRotR").onclick = function () { molRotate(1); };
$("molZoomIn").onclick = function () { molZoom(true); };
$("molZoomOut").onclick = function () { molZoom(false); };
// 等值面/透明度 oninput 实时更新（rAF 节流）
let molDensityUpdateScheduled = false;
function scheduleMolDensityUpdate() {
  if (molDensityUpdateScheduled) return;
  molDensityUpdateScheduled = true;
  requestAnimationFrame(function () {
    molDensityUpdateScheduled = false;
    updateMolIsosurface();
  });
}

$("molReset").onclick = resetMolView;
$("molPickClear").onclick = function () { molClearMeasure(); };
$("molPickColor").oninput = molApplyAtomStyle;
$("molPickSize").oninput = function () { molApplyAtomStyle(); };
$("molPickSizeRange").oninput = function () {
  const num = $("molPickSize");
  if (num) num.value = this.value;
  molApplyAtomStyle();
};
$("molPickSizeBtn").onclick = function () { molToggleNumPop("molPickSize", this); };
$("molPickReset").onclick = molResetPickSettings;
molSyncClearButton();
$("molIsoRange").oninput = function () {
  $("molIsoValue").value = this.value;
  $("molIsoValLabel").textContent = Number(this.value).toPrecision(4);
  scheduleMolDensityUpdate();
};
$("molIsoRange").onchange = updateMolIsosurface;
$("molIsoValue").onchange = function () {
  const range = $("molIsoRange");
  range.value = this.value;
  this.value = range.value;
  $("molIsoValLabel").textContent = Number(range.value).toPrecision(4);
  updateMolIsosurface();
};
$("molOpacityRange").oninput = function () {
  $("molOpacityValue").value = this.value;
  $("molOpacityValLabel").textContent = Number(this.value).toFixed(2);
  scheduleMolDensityUpdate();
};
$("molOpacityRange").onchange = updateMolIsosurface;
$("molOpacityValue").onchange = function () {
  const range = $("molOpacityRange");
  range.value = this.value;
  this.value = range.value;
  $("molOpacityValLabel").textContent = Number(range.value).toFixed(2);
  updateMolIsosurface();
};
// 密度控件弹层切换
document.querySelectorAll(".mol-density-pop").forEach(function (btn) {
  btn.onclick = function (ev) {
    ev.stopPropagation();
    const field = btn.closest(".mol-density-field");
    const panelId = field.getAttribute("data-panel");
    const panel = document.getElementById(panelId);
    const wasShow = panel.classList.contains("show");
    closeMolDensityPanels();
    if (!wasShow) {
      panel.classList.add("show");
      btn.classList.add("active");
      // 确保弹层不超出视口顶部
      requestAnimationFrame(function () {
        const rect = panel.getBoundingClientRect();
        if (rect.top < 6) {
          panel.style.bottom = "auto";
          panel.style.top = "calc(100% + 6px)";
        }
      });
    }
  };
});
// 点击外部关闭弹层
document.addEventListener("click", function (ev) {
  if (!ev.target.closest(".mol-density-field")) closeMolDensityPanels();
  if (!ev.target.closest(".mol-dd")) {
    document.querySelectorAll(".mol-dd.open").forEach(function (d) { d.classList.remove("open"); });
  }
});
$("molPlay").onclick = function () {
  if (MC.timer) { stopMolPlay(); return; }
  startMolPlay();
};
$("molPrev").onclick = function () { stopMolPlay(); showMolFrame(MC.index - 1); };
$("molNext").onclick = function () { stopMolPlay(); showMolFrame(MC.index + 1); };
$("molRange").oninput = function () { stopMolPlay(); showMolFrame(Number(this.value)); };
/* 空白点击不关闭弹窗（按需求移除），仅 ESC 或关闭按钮退出 */
$("btnQuickClose").onclick = closeQuickWithConfirm;
$("btnNewText").onclick = openNewText;
$("btnNewDir").onclick = openNewDir;
document.addEventListener("click", closeMenu);
document.addEventListener("click", function (ev) {
  const panel = $("molPickPanel");
  if (!panel || panel.classList.contains("hidden")) { molClosePickPops(); return; }
  if (panel.contains(ev.target)) {
    if (!ev.target.closest(".mol-pick-pop") && !ev.target.closest(".mol-pick-num-btn")) molClosePickPops();
    return;
  }
  molClosePickPops();
  const win = panel.closest(".mol-win");
  if (win && win.contains(ev.target)) molHidePickPanel();
});
document.addEventListener("keydown", function (event) {
  if (event.key !== "Escape") return;
  if (!$("molSaveBox").classList.contains("hidden")) { closeMolSave(); return; }
  if (!$("fileMenu").classList.contains("hidden")) { closeMenu(); return; }
  const hasDensityPanel = document.querySelector(".mol-density-panel.show");
  if (hasDensityPanel) { closeMolDensityPanels(); return; }
  const pickPanel = $("molPickPanel");
  if (pickPanel && !pickPanel.classList.contains("hidden")) { molHidePickPanel(); return; }
  const openMask = activeMask && !activeMask.classList.contains("hidden")
    ? activeMask : document.querySelector(".mol-mask:not(.hidden)");
  if (openMask && openMask.dataset.baseId === "quickView") { closeQuickWithConfirm(); return; }
  if (openMask && openMask.dataset.baseId === "molView") closeStructureWithConfirm();
});
window.addEventListener("resize", function () {
  molClampGizmo();
  if (!MC.viewer) return;
  MC.viewer.resize();
  MC.viewer.render();
});
// 页面尺寸变化后，重新约束所有文件浮窗，使顶栏边沿中心点仍在页面内。
window.addEventListener("resize", function () {
  Array.prototype.forEach.call(document.querySelectorAll(".mol-mask"), function (m) {
    if (m._reclamp) m._reclamp();
  });
});

(function () {
  const letters = Array.prototype.slice.call(document.querySelectorAll(".wordmark span"));
  function rand(min, max) { return Math.random() * (max - min) + min; }
  function pop(el) {
    const rot = (Math.random() < 0.5 ? -1 : 1) * rand(12, 30);
    const scale = rand(0.72, 1.45);
    const skew = rand(-12, 12);
    const dx = rand(-4, 4);
    const dy = rand(-4, 4);
    el.style.transition = "transform .3s cubic-bezier(.34, 1.56, .64, 1)";
    el.style.transform = "translate(" + dx.toFixed(1) + "px, " + dy.toFixed(1) + "px) rotate(" + rot.toFixed(1) + "deg) scale(" + scale.toFixed(2) + ") skew(" + skew.toFixed(1) + "deg)";
    clearTimeout(el._timer);
    el._timer = setTimeout(function () {
      el.style.transition = "transform .5s cubic-bezier(.34, 1.56, .64, 1)";
      el.style.transform = "";
    }, 420);
  }
  letters.forEach(function (el) {
    el.addEventListener("mouseenter", function () { pop(el); });
    el.addEventListener("click", function () { pop(el); });
  });
})();

(async function init() {
  try {
    const info = await api("/api/info");
    applyInfo(info);
    await load("");
    startTerminal();
    state.watchTimer = setInterval(watchDir, 2000);
  } catch (err) {
    toast(err.message, true);
  }
})();

/* ---------- MIT License：打字机浮层 ---------- */
(function initLicense() {
  const LICENSE_LINES = [
    "MIT License",
    "",
    "Copyright (c) 2026 Kan",
    "",
    "Permission is hereby granted, free of charge, to any person obtaining a copy",
    "of this software and associated documentation files (the \\"Software\\"), to deal",
    "in the Software without restriction, including without limitation the rights",
    "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell",
    "copies of the Software, and to permit persons to whom the Software is",
    "furnished to do so, subject to the following conditions:",
    "",
    "The above copyright notice and this permission notice shall be included in all",
    "copies or substantial portions of the Software.",
    "",
    "THE SOFTWARE IS PROVIDED \\"AS IS\\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR",
    "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,",
    "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE",
    "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER",
    "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,",
    "OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE",
    "SOFTWARE."
  ];
  const LICENSE_TEXT = LICENSE_LINES.join("\\n");
  const overlay = $("licenseOverlay");
  const out = $("licenseText");
  if (!overlay || !out) return;
  let timer = null;

  function hide() {
    if (timer) { clearInterval(timer); timer = null; }
    overlay.classList.add("hidden");
  }
  function show(ev) {
    if (ev) { ev.preventDefault(); ev.stopPropagation(); }
    if (timer) { clearInterval(timer); timer = null; }
    // 先把全部行放进 DOM 并隐藏，首行从一开始就在全文显示时的最终位置。
    out.textContent = "";
    const frag = document.createDocumentFragment();
    LICENSE_LINES.forEach(function (line) {
      const span = document.createElement("span");
      span.className = "license-line";
      span.textContent = line;
      frag.appendChild(span);
    });
    out.appendChild(frag);
    const rows = out.querySelectorAll(".license-line");
    out.scrollTop = 0;
    overlay.classList.remove("hidden");
    let i = 0;
    function reveal() {
      if (i >= rows.length) { clearInterval(timer); timer = null; return; }
      const row = rows[i];
      row.classList.add("shown");
      // 仅当屏幕放不下时，才向上移动到刚显示的行。
      const bottom = row.offsetTop + row.offsetHeight;
      if (bottom > out.scrollTop + out.clientHeight) out.scrollTop = bottom - out.clientHeight;
      else if (row.offsetTop < out.scrollTop) out.scrollTop = row.offsetTop;
      i += 1;
    }
    reveal();
    if (i < rows.length) timer = setInterval(reveal, 80);
  }
  ["sideMit", "footMit"].forEach(function (id) {
    const el = $(id);
    if (!el) return;
    el.addEventListener("click", show);
    el.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") show(e);
    });
  });
  overlay.addEventListener("click", hide);
  document.addEventListener("click", function (ev) {
    if (overlay.classList.contains("hidden")) return;
    if (ev.target.closest && ev.target.closest(".license-link")) return;
    hide();
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && !overlay.classList.contains("hidden")) hide();
  });
})();
</script>
</html>
"""


# ------------------------------------------------------------------ 启动 ---
class _Server(ThreadingHTTPServer):
    """按监听地址自动选择 IPv4 / IPv6。"""

    def __init__(self, host, port, handler):
        try:
            family = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][0]
        except socket.gaierror:
            family = socket.AF_INET
        self.address_family = family
        super().__init__((host, port), handler)


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
        os._exit(0)

    sigs = (signal.SIGTERM,) if no_hup else (signal.SIGHUP, signal.SIGTERM)
    for sig in sigs:
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


def _serve(host, port, token):
    _CONF["token"] = token
    _CONF["no_token"] = not token
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:  # pragma: no cover - 老版本 Python
        pass
    handler = _make_handler()
    httpd = _Server(host, port, handler)
    _install_signal_cleanup(port)
    _start_terminal_watch(httpd)
    print("McTa 文件服务")
    print("  地址    " + _url(host, port, token))
    print("  运行目录 " + str(Path(_CONF["start"]).resolve()))
    print("  账户    " + _CONF["user"])
    print("  token   " + ("未启用（-N：直接凭地址和端口访问）" if not token
                          else "每次启动随机生成，重启后旧链接失效"))
    print("  停止    Ctrl+C")
    print("")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
        # 后台服务自行退出时，清掉自己的 PID 记录
        try:
            path = _pid_path(port)
            if path.exists() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                path.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


def _start_background(host, port, token, log=None, no_hup=False):
    if _port_open(host, port):
        print("ERROR: 端口 %d 已被其他程序占用，可用 -p 换一个端口。" % port, file=sys.stderr)
        return 2

    cmd = [sys.executable, "-m", "mcta.server", "--serve",
           "--host", host, "-p", str(port)]
    env = dict(os.environ, **{TOKEN_ENV: token,
                              ROOT_ENV: str(Path.cwd().resolve()),
                              SKIP_CONFIRM_ENV: "1"})
    if not token:
        env[NO_TOKEN_ENV] = "1"
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

    _pid_path(port).write_text(str(proc.pid), encoding="utf-8")

    for _ in range(50):
        time.sleep(0.2)
        info = _probe(host, port, token, timeout=0.5)
        if info:
            print("McTa 文件服务已在后台启动")
            print("  地址    " + _url(host, port, token))
            print("  运行目录 " + info["root"])
            print("  账户    " + str(info["user"]))
            print("  token   " + ("未启用（-N：直接凭地址和端口访问）" if not token
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
    return b"mcta.server" in raw or b"mt.server" in raw


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
        pid = int(path.read_text(encoding="utf-8").strip())
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


def _stop(port):
    path = _pid_path(port)
    if not path.exists():
        print("没有找到端口 %d 的后台服务记录。" % port)
        return 2
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        print("PID 文件损坏，已删除。")
        return 2

    if not _pid_alive(pid) or not _pid_is_server(pid):
        path.unlink(missing_ok=True)
        print("端口 %d 上的服务已不在运行（进程 %d），已清理记录。" % (port, pid))
        return 0

    if not _terminate_pid(pid):
        print("停止失败：进程 %d 无法终止。" % pid, file=sys.stderr)
        return 1
    path.unlink(missing_ok=True)
    print("已停止端口 %d 上的服务（进程 %d）。" % (port, pid))
    return 0


def _server_records():
    """遍历本用户的 PID 记录，返回 [(端口, 进程号, 是否存活)]，按端口升序。"""
    records = []
    for path in _state_dir().glob("server-*.pid"):
        try:
            port = int(path.stem.split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            records.append((port, 0, False))
            continue
        records.append((port, pid, _pid_alive(pid) and _pid_is_server(pid)))
    records.sort()
    return records


def _status():
    """列出本用户所有端口的 mt.server 后台服务。"""
    records = _server_records()
    if not records:
        print("当前用户没有 mt.server 的后台服务记录。")
        return 0
    print("%-8s %-8s %s" % ("端口", "进程", "状态"))
    running = 0
    for port, pid, alive in records:
        if alive:
            running += 1
            state = "运行中"
        else:
            state = "已退出（记录过期）"
        print("%-8d %-8s %s" % (port, pid if pid else "-", state))
    print("共 %d 个端口有记录，其中 %d 个运行中。" % (len(records), running))
    return 0


def _stop_all():
    """停止本用户所有端口上运行的 mt.server。"""
    records = _server_records()
    if not records:
        print("当前用户没有 mt.server 的后台服务记录。")
        return 0
    code = 0
    for port, _, _ in records:
        code = max(code, _stop(port))
    return code


def _confirm_risk(message):
    """危险启动选项的确认：必须在终端输入 yes 或 YES。"""
    print("WARNING: " + message, flush=True)
    try:
        ans = input("确认继续请输入 yes 或 YES：").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消启动。", file=sys.stderr)
        return False
    if ans.lower() == "yes":
        return True
    print("输入不是 yes/YES，已取消启动。", file=sys.stderr)
    return False


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
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT,
                        help="监听端口，默认 %d" % DEFAULT_PORT)
    parser.add_argument("-f", "--serve", action="store_true",
                        help="前台运行（在当前终端直接提供服务，不转入后台）")
    parser.add_argument("-o", "--log", nargs="?", const="", default=None, metavar="PATH",
                        help="输出日志文件（默认不输出）；-o 不带路径时写到当前目录 mcta-server-<端口>.log")
    parser.add_argument("-d", "--directory", default=None, metavar="PATH",
                        help="运行目录（页面起始目录），默认为当前目录")
    parser.add_argument("-N", "--no-token", action="store_true",
                        help="不启用 token 鉴权（需输入 yes 确认），直接用地址和端口访问")
    parser.add_argument("-L", "--host", default=DEFAULT_HOST, metavar="HOST",
                        help="监听地址，默认 127.0.0.1；对外监听（如 0.0.0.0）需输入 yes 确认")
    parser.add_argument("-Y", "--yes", action="store_true",
                        help="跳过危险启动选项的输入确认（配合 -L 非回环地址或 -N 使用）")
    parser.add_argument("--status", action="store_true",
                        help="列出本用户所有端口上运行的 mt.server")
    parser.add_argument("-S", "--stop", action="store_true",
                        help="停止后台服务；与 --all 连用时停止本用户所有端口的服务")
    parser.add_argument("--all", action="store_true",
                        help="配合 -S 使用：停止本用户所有端口上运行的 mt.server")
    parser.add_argument("--no-hup", action="store_true",
                        help="终端关闭后服务继续运行（忽略 SIGHUP，不跟随启动终端退出）；只能用 -S 或 -S --all 终止")
    args = parser.parse_args(argv)

    if args.version:
        print(version_string())
        return 0
    if args.status:
        return _status()
    if args.all and not args.stop:
        print("ERROR: --all 只能与 -S/--stop 一起使用。", file=sys.stderr)
        return 2
    if not 0 < args.port < 65536:
        print("ERROR: 端口需在 1–65535 之间。", file=sys.stderr)
        return 2
    if args.stop:
        return _stop_all() if args.all else _stop(args.port)

    # 运行目录：-d 指定或默认当前目录，必须是存在的目录
    if args.directory is not None:
        target = Path(args.directory).expanduser()
        try:
            target = target.resolve()
        except OSError as exc:
            print("ERROR: 无法解析目录 %s：%s" % (args.directory, exc), file=sys.stderr)
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

    no_token = args.no_token or os.environ.get(NO_TOKEN_ENV) == "1"

    # 危险选项确认：-L 非回环地址、-N 无鉴权各确认一次，同时使用则需输入两次。
    # -Y/--yes 可跳过所有输入确认，适合脚本化或 CI 场景。
    # 后台子进程（--serve）由父进程拉起，这里跳过，避免重复询问。
    if os.environ.get(SKIP_CONFIRM_ENV) != "1" and not args.yes:
        if not _is_loopback(args.host):
            if not _confirm_risk("已绑定 %s（非回环地址）：能访问该端口的人都可以读写文件并执行命令。"
                                 % args.host):
                return 3
        if no_token:
            if not _confirm_risk("已启用 -N（不校验 token）：任何能访问该端口的人都能读写文件并执行命令。"):
                return 3

    token = "" if no_token else (os.environ.get(TOKEN_ENV) or secrets.token_urlsafe(24))

    _stop_existing(args.port)

    try:
        return _serve(args.host, args.port, token) if args.serve \
            else _start_background(args.host, args.port, token,
                                   log=_resolve_log(args.log, args.port),
                                   no_hup=args.no_hup)
    except OSError as exc:
        print("ERROR: 无法监听 %s:%d（%s）" % (args.host, args.port, exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
