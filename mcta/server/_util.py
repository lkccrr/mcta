"""HTTP 服务共用常量、文件工具与 3D 渲染缓存。

从 _handlers.py 抽出，供请求处理逻辑复用；不依赖 Handler 状态。
"""

import codecs
import hashlib
from collections import OrderedDict
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

from ._structure import (
    DENSITY_NAMES, DENSITY_PREFIXES, JSON_EXTS, XML_DOC_EXTS,
    STRUCT_EXTS, STRUCT_NAMES, STRUCT_PREFIXES, _is_structure,
)
from ._remote import RemoteNotFound

MAX_EDIT_BYTES = 2 * 1024 * 1024


# 超过该体积且能解码为文本的文件不再整篇塞进页面，改按行分段加载。
LARGE_TEXT_BYTES = MAX_EDIT_BYTES


MAX_INPUT = 64 * 1024


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


MAX_TABLE_ROWS = 2000


ASSET_DIR = Path(__file__).resolve().parent


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


def _remote_missing(exc):
    """SFTP stat 抛出的“不存在”错误（paramiko 各版本文案不同）。"""
    text = str(exc).lower()
    return (isinstance(exc, (FileNotFoundError, RemoteNotFound))
            or "no such file" in text or "not found" in text or "不存在" in text)


def _parse_range(size, rng):
    """解析 HTTP Range；越界返回 None。无 Range 时返回完整文件区间。"""
    start, end, status = 0, max(0, size - 1), 200
    rng = (rng or "").strip()
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", rng) if rng else None
    content_range = None
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
                return None
            end = min(end, size - 1)
            status = 206
            content_range = "bytes %d-%d/%d" % (start, end, size)
    return start, end, status, content_range


# --------------------------------------------------------- 大文本分段加载 ---
# 大文本像音视频一样只加载当前视窗：服务端建立行索引缓存，前端按行号请求窗口。
TEXT_INDEX_STEP = 1000          # 每 1000 行记一个字节偏移锚点
TEXT_READ_MAX_BYTES = 8 * 1024 * 1024
TEXT_LINE_MAX_CHARS = 20000
MAX_TEXT_INDEXES = 8

_TEXT_INDEX_CACHE = OrderedDict()
_TEXT_INDEX_LOCK = threading.Lock()


class TextIndex:
    """大文本文件的一次性行索引；只在 size/mtime 变化时重建。"""

    __slots__ = ("total_lines", "checkpoints", "encoding", "newline", "size", "mtime")

    def __init__(self, total_lines, checkpoints, encoding, newline, size, mtime):
        self.total_lines = total_lines
        self.checkpoints = checkpoints
        self.encoding = encoding
        self.newline = newline
        self.size = size
        self.mtime = mtime


def _text_encoding(sample):
    """返回 (codec, newline_bytes, bom_length)，供整篇分段解码保持一致。"""
    if sample.startswith(codecs.BOM_UTF32_LE):
        return "utf-32-le", b"\n\x00\x00\x00", 4
    if sample.startswith(codecs.BOM_UTF32_BE):
        return "utf-32-be", b"\x00\x00\x00\n", 4
    if sample.startswith(codecs.BOM_UTF8):
        return "utf-8-sig", b"\n", 3
    if sample.startswith(codecs.BOM_UTF16_LE):
        return "utf-16-le", b"\n\x00", 2
    if sample.startswith(codecs.BOM_UTF16_BE):
        return "utf-16-be", b"\x00\n", 2
    try:
        text = sample.decode("utf-8")
        if "\x00" not in text:
            return "utf-8", b"\n", 0
    except UnicodeDecodeError:
        pass
    if b"\x00" in sample[:4096] and len(sample) % 2 == 0:
        if _decode_utf16(sample, le=True) is not None:
            return "utf-16-le", b"\n\x00", 0
        if _decode_utf16(sample, le=False) is not None:
            return "utf-16-be", b"\x00\n", 0
    return "gb18030", b"\n", 0


def _sample_bytes(opener, size, length=64 * 1024):
    fh = opener()
    try:
        fh.seek(0)
        return fh.read(min(size, length))
    finally:
        fh.close()


def _build_text_index(key, opener, size, mtime):
    sample = _sample_bytes(opener, size)
    encoding, newline, _bom = _text_encoding(sample)

    checkpoints = [(0, 0)]
    count = 0
    overlap = max(0, len(newline) - 1)
    step = max(1024, 1024 * 1024 - overlap)
    fh = opener()
    try:
        scan = 0
        while scan < size:
            scan_start = scan
            fh.seek(scan)
            chunk = fh.read(step + overlap)
            if not chunk:
                break
            start = 0
            while True:
                pos = chunk.find(newline, start)
                if pos < 0:
                    break
                absolute = scan + pos
                # 相邻块有重叠：只统计本块起点之后的换行，避免重复计数。
                if absolute >= scan_start and absolute + len(newline) <= size:
                    count += 1
                    if count % TEXT_INDEX_STEP == 0:
                        checkpoints.append((count, absolute + len(newline)))
                start = pos + len(newline)
            advance = max(1, len(chunk) - overlap)
            scan += advance
    finally:
        fh.close()

    tail = b""
    if size:
        with_tail = opener()
        try:
            with_tail.seek(max(0, size - len(newline)))
            tail = with_tail.read(len(newline))
        finally:
            with_tail.close()
    total = count + (0 if tail.endswith(newline) else 1)
    return TextIndex(max(1, total), checkpoints, encoding, newline, size, mtime)


def _text_index(key, opener, size, mtime):
    """按路径+size+mtime 缓存行索引；文件变化后自动重建。"""
    cache_key = (str(key), int(size), int(mtime or 0))
    with _TEXT_INDEX_LOCK:
        cached = _TEXT_INDEX_CACHE.get(cache_key)
        if cached is not None:
            _TEXT_INDEX_CACHE.move_to_end(cache_key)
            return cached
    index = _build_text_index(key, opener, size, mtime)
    with _TEXT_INDEX_LOCK:
        _TEXT_INDEX_CACHE[cache_key] = index
        _TEXT_INDEX_CACHE.move_to_end(cache_key)
        while len(_TEXT_INDEX_CACHE) > MAX_TEXT_INDEXES:
            _TEXT_INDEX_CACHE.popitem(last=False)
    return index


def _text_lines(index, opener, start, count):
    """从最近的锚点读取一段字节，解码后返回指定行号范围。"""
    total = index.total_lines
    start = max(0, min(int(start), total - 1))
    count = max(1, min(int(count), 2000))
    base_line, base_offset = index.checkpoints[0]
    for line, offset in index.checkpoints:
        if line <= start:
            base_line, base_offset = line, offset
        else:
            break

    fh = opener()
    data = b""
    eof = False
    try:
        fh.seek(base_offset)
        while len(data) < TEXT_READ_MAX_BYTES:
            chunk = fh.read(min(256 * 1024, TEXT_READ_MAX_BYTES - len(data)))
            if not chunk:
                eof = True
                break
            data += chunk
    finally:
        fh.close()

    text = data.decode(index.encoding, errors="replace").lstrip("\ufeff")
    parts = text.splitlines()
    if not eof and len(data) >= TEXT_READ_MAX_BYTES and parts:
        parts.pop()  # 可能截在半行/半字符，丢掉末段
    lines = []
    for i, value in enumerate(parts, start=base_line):
        if len(lines) >= count:
            break
        if i < start:
            continue
        if len(value) > TEXT_LINE_MAX_CHARS:
            value = value[:TEXT_LINE_MAX_CHARS] + "…"
        lines.append(value)
    return start, lines


# ------------------------------------------------------------------ 服务 ---

# ------------------------------------------------- 3D 渲染远端通道（第五通道） ---
# 只用于“结构/体数据渲染”请求；终端、目录、上传、下载仍走原有四条通道。
REMOTE_RENDER_MIN_BYTES = max(
    0, int(os.environ.get("MCTA_REMOTE_RENDER_MIN_MB", "8") or 8)) * 1024 * 1024
REMOTE_RENDER_TIMEOUT = 30
# 整体预算：单次 read 超时会在持续输出时不断重置，这里限制一次渲染的总时长，
# 防止慢请求长期占用 slot。
REMOTE_RENDER_TOTAL_SECONDS = max(
    5.0, float(os.environ.get("MCTA_RENDER_TOTAL_SECONDS", "60") or 60))
REMOTE_RENDER_SLOTS = 2
# 渲染缓存：gzip 压缩存储 + LRU 容量上限，避免缓存目录无限增长。
RENDER_CACHE_COMPRESS_MIN = 64 * 1024
RENDER_CACHE_COMPRESS_LEVEL = 6
RENDER_CACHE_MAX_BYTES = max(
    0, int(os.environ.get("MCTA_RENDER_CACHE_MAX_MB", "512") or 512)) * 1024 * 1024
_RENDER_CACHE_ROOT = Path(os.environ.get("XDG_CACHE_HOME")
                          or str(Path.home() / ".cache")) / "mcta" / "render-cache"
# 淘汰时保留最近 N 秒内的条目，避免删掉正在流式读取/刚写入的缓存。
_RENDER_CACHE_FRESH_SECONDS = max(
    0.0, float(os.environ.get("MCTA_CACHE_FRESH_SECONDS", "30") or 30))
_RENDER_CACHE_PART_MAX_AGE = 3600  # 残留 .part 超过 1 小时视为垃圾
_RENDER_SEMS = {}
_RENDER_SEMS_LOCK = threading.Lock()
_RENDER_CACHE_PRUNE_LOCK = threading.Lock()


def _render_semaphore(host):
    with _RENDER_SEMS_LOCK:
        sem = _RENDER_SEMS.get(host)
        if sem is None:
            sem = threading.Semaphore(REMOTE_RENDER_SLOTS)
            _RENDER_SEMS[host] = sem
        return sem


def _is_render_structure(path):
    """按文件名判断是否为可远端渲染的结构/体数据（不读取文件内容）。"""
    item = Path(str(path))
    if item.suffix.lower() in JSON_EXTS or item.suffix.lower() in XML_DOC_EXTS:
        return False
    if item.suffix.lower() in STRUCT_EXTS:
        return True
    name = item.name.upper()
    if name in STRUCT_NAMES or name in DENSITY_NAMES or name.startswith(STRUCT_PREFIXES):
        return True
    return any(name.startswith(prefix + "-") or name.startswith(prefix + "_")
               for prefix in DENSITY_PREFIXES)


def _cache_unlink(path):
    """删除缓存文件；失败静默跳过并记录一条 WARNING，不影响请求。"""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        print("[render-cache] WARNING 删除失败 %s: %s" % (
            path.name, str(exc)[:120]), file=sys.stderr, flush=True)


def _render_cache_dir(remote_path, host=""):
    """按远端主机 + 绝对路径隔离；不同主机的同名文件不会互相污染。"""
    seed = (str(host or "") + "\0" + str(remote_path)).encode("utf-8")
    key = hashlib.sha256(seed).hexdigest()[:24]
    return _RENDER_CACHE_ROOT / key


def _render_cache_entry(remote_path, mtime, size, frames, limit=0, host=""):
    """key = 远端路径 + mtime + size + frames + limit，且按主机隔离。"""
    name = "%d-%d-%d-%d" % (
        int(mtime or 0), int(size or 0), 1 if frames else 0, int(limit or 0))
    base = _render_cache_dir(remote_path, host) / name
    return base, base.with_name(name + ".body"), base.with_name(name + ".meta")


def _cache_body_raw_size(body, encoding):
    """返回 body 解压后的字节数；gzip 读尾部 ISIZE，避免每次命中都全量解压。"""
    try:
        if encoding == "gzip":
            if body.stat().st_size < 18:
                return -1
            with body.open("rb") as fh:
                if fh.read(2) != b"\x1f\x8b":
                    return -1
                fh.seek(-4, 2)
                return int.from_bytes(fh.read(4), "little")
        return body.stat().st_size
    except OSError:
        return -1


def _render_cache_load(remote_path, mtime, size, frames, limit=0, host=""):
    """返回 (body_path, content_type, encoding, raw_size)，body 不再整份读入内存。

    meta 中的 raw_size 与 body 解压后大小不一致时视为损坏：删除整条并返回 None。
    """
    _base, body, meta = _render_cache_entry(
        remote_path, mtime, size, frames, limit, host)
    if not (body.is_file() and meta.is_file()):
        return None
    try:
        info = json.loads(meta.read_text(encoding="utf-8"))
        encoding = str(info.get("encoding") or "")
        try:
            raw_size = int(info.get("raw_size", -1))
        except (TypeError, ValueError):
            raw_size = -1
        actual = _cache_body_raw_size(body, encoding)
        if raw_size < 0 or (actual >= 0 and raw_size % (1 << 32) != actual):
            # 元数据与实体不匹配：删除 body/meta，交给调用方重新拉取远端。
            _cache_unlink(body)
            _cache_unlink(meta)
            return None
        # LRU：命中时刷新 meta 的 mtime，作为淘汰顺序。
        try:
            os.utime(str(meta), None)
        except OSError:
            pass
        return (str(body),
                str(info.get("content_type") or "application/json; charset=utf-8"),
                encoding, raw_size)
    except (OSError, ValueError):
        _cache_unlink(body)
        _cache_unlink(meta)
        return None


def _render_cache_prune():
    """跨主机按访问时间 LRU 淘汰，直到降至上限的 80%；成对删除 body/meta。

    统计所有子目录的 *.body，顺带清理孤儿文件与过期的 .part；
    淘汰跳过最近 N 秒内的条目，给正在流式读取的请求留出窗口。
    """
    if not _RENDER_CACHE_ROOT.is_dir():
        return
    with _RENDER_CACHE_PRUNE_LOCK:
        now = time.time()
        entries = []
        orphans = []
        total = 0
        try:
            folders = [p for p in _RENDER_CACHE_ROOT.iterdir() if p.is_dir()]
        except OSError:
            return
        for folder in folders:
            bodies, metas = {}, {}
            try:
                for p in folder.iterdir():
                    if p.name.endswith(".body"):
                        bodies[p.name[:-5]] = p
                    elif p.name.endswith(".meta"):
                        metas[p.name[:-5]] = p
                    elif p.name.endswith(".part"):
                        try:
                            if now - p.stat().st_mtime > _RENDER_CACHE_PART_MAX_AGE:
                                orphans.append(p)
                        except OSError:
                            pass
            except OSError:
                continue
            for key in set(bodies) | set(metas):
                body, meta = bodies.get(key), metas.get(key)
                if body is None or meta is None:
                    # 孤儿：存在的那一半（或两半）都清掉。
                    orphans.extend(p for p in (body, meta) if p is not None)
                    continue
                try:
                    accessed = meta.stat().st_mtime
                    total += body.stat().st_size
                except OSError:
                    continue
                entries.append((accessed, folder, body, meta))
        for path in orphans:
            _cache_unlink(path)
        if RENDER_CACHE_MAX_BYTES <= 0 or total <= RENDER_CACHE_MAX_BYTES:
            return
        target = int(RENDER_CACHE_MAX_BYTES * 0.8)
        entries.sort(key=lambda item: item[0])
        for accessed, folder, body, meta in entries:
            if total <= target:
                break
            if now - accessed < _RENDER_CACHE_FRESH_SECONDS:
                continue
            for path in (body, meta):
                try:
                    total -= path.stat().st_size
                except OSError:
                    pass
                _cache_unlink(path)
        for folder in folders:
            try:
                folder.rmdir()
            except OSError:
                pass


def _invalidate_render_cache(remote_path, host=""):
    """结构写回后清掉该文件所有 frames/limit 变体，避免下次打开看到旧画面。"""
    try:
        shutil.rmtree(str(_render_cache_dir(remote_path, host)), ignore_errors=True)
    except OSError as exc:
        print("[render-cache] WARNING 清理失败 %s: %s" % (
            str(remote_path)[:120], str(exc)[:120]), file=sys.stderr, flush=True)
