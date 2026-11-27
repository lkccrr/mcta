"""HTTP 路由与文件服务。

mt.server 从 mcta/server/__init__.py 拆出：BaseHTTPRequestHandler 实现、
静态资源/文件浏览/编辑/上传/下载/结构预览等 API。
页面模板与静态资源在 _page.py 及同级 page.html / app.css / app.js 中，
启动与进程管理仍留在 __init__.py。
"""

import base64
import codecs
import gzip
import hashlib
import http.client
import io
import json
import mimetypes
import os
import platform
import posixpath
import queue
import re
import shutil
import socket
import socketserver
import stat
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from mcta import __version__

from ._page import PAGE

from ._structure import (
    DENSITY_NAMES, DENSITY_PREFIXES, JSON_EXTS, LAMMPS_DATA_EXTS,
    MAX_DENSITY_BYTES, MAX_DENSITY_POINTS, MAX_STRUCT_BYTES,
    MAX_STRUCT_FRAMES, MAX_TRAJ_ATOMS, STRUCT_EXTS, STRUCT_NAMES,
    STRUCT_PREFIXES, _density_options, _is_structure, _is_vasp_density,
    _lammps_data_style, _read_atoms, _read_frames, _read_vasp_density,
    _insert_atom, _restore_vasp_coord_format, _vasp_coord_info,
)
from ._remote import DEFAULT_RENDER_SOCKET, RemoteError, RemoteNotFound, remote_log
from ._terminal import (
    TOKEN_COOKIE, _CONF, _HAS_PTY, _TERMINALS, _TERMINALS_LOCK, _clean_sid,
    _terminal_for, _token_matches,
)

from ._util import (
    MAX_EDIT_BYTES,
    LARGE_TEXT_BYTES,
    TEXT_INDEX_STEP,
    MAX_INPUT,
    IMAGE_EXTS,
    PDF_EXTS,
    AUDIO_EXTS,
    VIDEO_EXTS,
    MEDIA_EXTS,
    MEDIA_MIMES,
    MARKDOWN_EXTS,
    TABLE_EXTS,
    MAX_TABLE_ROWS,
    ASSET_DIR,
    _kind,
    _printable_ratio,
    _decode_utf16,
    _decode,
    _mtime,
    _remote_missing,
    _parse_range,
    _sample_bytes,
    _text_index,
    _text_lines,
    REMOTE_RENDER_MIN_BYTES,
    REMOTE_RENDER_TIMEOUT,
    REMOTE_RENDER_TOTAL_SECONDS,
    REMOTE_RENDER_SLOTS,
    RENDER_CACHE_COMPRESS_MIN,
    RENDER_CACHE_COMPRESS_LEVEL,
    RENDER_CACHE_MAX_BYTES,
    _RENDER_CACHE_ROOT,
    _RENDER_SEMS,
    _RENDER_SEMS_LOCK,
    _render_semaphore,
    _is_render_structure,
    _render_cache_dir,
    _render_cache_entry,
    _render_cache_load,
    _render_cache_prune,
    _invalidate_render_cache,
)

class _RenderFileError(Exception):
    """远端返回非 200：单个文件的问题，不关闭共享渲染隧道。"""

    def __init__(self, status):
        self.status = int(status)
        super().__init__("远端返回 HTTP %d" % self.status)


class _RenderTimeoutError(Exception):
    """整体渲染预算耗尽：请求级问题，不关闭共享渲染隧道。"""


def _make_handler():

    # 启动时先按容量上限整理一次旧缓存，不必等下一次写入才淘汰。
    _render_cache_prune()

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

        def _send_cached_render(self, body_path, content_type, encoding, raw_size=None):
            """流式发送缓存的渲染结果；gzip 在服务端解压，客户端无需感知。

            Content-Length 用解压后的字节数 raw_size；gzip 缓存文件是压缩后的大小，
            不能冒充。raw_size 无效时按损坏处理（返回 False 让调用方重新请求远端）。
            """
            try:
                size = int(raw_size) if raw_size is not None else -1
            except (TypeError, ValueError):
                size = -1
            if size < 0:
                # 非 gzip 可安全回退到磁盘大小；gzip 不能用压缩大小冒充解压大小。
                if encoding == "gzip":
                    return False
                try:
                    size = Path(body_path).stat().st_size
                except OSError:
                    return False
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Mcta-Render-Cache", "hit")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            if self.command == "HEAD":
                return True
            try:
                opener = gzip.open if encoding == "gzip" else open
                with opener(str(body_path), "rb") as fh:
                    while True:
                        chunk = fh.read(64 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except (OSError, EOFError):
                pass
            return True

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
            parsed = _parse_range(size, self.headers.get("Range"))
            if parsed is None:
                self._send(b"", "application/octet-stream", 416, [
                    ("Content-Range", "bytes */%d" % size),
                ])
                return
            start, end, status, content_range = parsed
            if content_range:
                headers.append(("Content-Range", content_range))
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

        def _send_remote_media(self, remote, rel, suffix):
            """流式发送远程音视频，只按浏览器请求读取当前播放区间，不落本地缓存。"""
            remote_path = remote.remote_for(rel)
            try:
                info = remote.stat_remote(remote_path)
                if not stat.S_ISREG(info.st_mode):
                    self._error("文件不存在", 404)
                    return
                size = int(info.st_size)
            except RemoteError as exc:
                self._handle_error(exc, 403)
                return
            except OSError as exc:
                self._error("无法读取远程文件：%s" % exc, 500)
                return

            content_type = (MEDIA_MIMES.get(suffix)
                            or mimetypes.guess_type(remote_path)[0]
                            or "application/octet-stream")
            parsed = _parse_range(size, self.headers.get("Range"))
            if parsed is None:
                self._send(b"", "application/octet-stream", 416, [
                    ("Content-Range", "bytes */%d" % size),
                ])
                return
            start, end, status, content_range = parsed
            length = 0 if size == 0 else end - start + 1

            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Disposition",
                             "inline; filename*=UTF-8''%s"
                             % quote(posixpath.basename(remote_path)))
            if content_range:
                self.send_header("Content-Range", content_range)
            self.end_headers()
            if self.command == "HEAD":
                return

            pos, remaining = start, length
            fh = None
            recovered = False
            try:
                fh = remote.open_remote(remote_path, size=size)
                fh.seek(pos)
                while remaining > 0:
                    try:
                        chunk = fh.read(min(64 * 1024, remaining))
                    except Exception as exc:
                        if recovered or not remote.is_conn_error(exc):
                            raise
                        # 传输中断：重连后从当前偏移继续，浏览器无需重新下载。
                        recovered = True
                        try:
                            fh.close()
                        except Exception:
                            pass
                        remote.reconnect()
                        fh = remote.open_remote(remote_path, size=size)
                        fh.seek(pos)
                        continue
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    pos += len(chunk)
                    remaining -= len(chunk)
            except (OSError, RemoteError):
                # 客户端取消拖动/关闭播放器时直接结束，不污染响应。
                pass
            finally:
                if fh is not None:
                    try:
                        fh.close()
                    except Exception:
                        pass

        def _error(self, message, status=400):
            self._json({"error": message}, status)

        def _handle_error(self, exc, status=400):
            """统一错误出口：路径不存在的异常一律回 404，其余保留原状态码。"""
            if getattr(exc, "not_found", False):
                status = 404
            self._error(str(exc), status)

        def _readonly_remote(self):
            if _CONF.get("remote_fs") is None:
                return False
            self._error("远程模式暂不支持此操作；新建目录/文本、上传、删除、文本编辑与 3D 状态存档可用，其余写入请通过 SSH 终端", 405)
            return True

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
            """页面起始目录：本地模式为运行目录，远程模式为服务器上的起始目录。

            远程文件本体仍缓存在本地临时目录，但页面路径、面包屑和终端 cd
            都必须使用远程绝对路径；不能把本地缓存路径暴露给前端。
            """
            remote = _CONF.get("remote_fs")
            if remote is not None:
                return Path(remote.root)
            return Path(_CONF["start"]).resolve()

        def _resolve(self, rel):
            """解析到运行目录/终端目录及其上级；.. 与符号链接逃逸一律拒绝。"""
            remote = _CONF.get("remote_fs")
            if remote is not None:
                try:
                    return remote.ensure(rel)
                except RemoteNotFound as exc:
                    err = ValueError(str(exc))
                    err.not_found = True
                    raise err
                except RemoteError as exc:
                    raise ValueError(str(exc))
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
            remote = _CONF.get("remote_fs")
            if remote is not None:
                return remote.rel(remote.remote_for_local(path))
            try:
                rel = path.relative_to(self._root_dir()).as_posix()
            except ValueError:
                return path.as_posix()
            return "" if rel == "." else rel

        def log_message(self, fmt, *args):
            # 正常执行日志（HTTP 访问等）一律不输出；-o 文件只保留启动/错误信息。
            return

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
                rel = (query.get("path") or [""])[0]
                # limit=N：轨迹只返回前 N 帧（首屏优先），partial 标记告知前端后台补全。
                try:
                    limit = max(0, min(MAX_STRUCT_FRAMES,
                                       int((query.get("limit") or ["0"])[0])))
                except (TypeError, ValueError):
                    limit = 0
                if not self._structure_remote(rel, frames, limit):
                    self._structure(rel, frames, limit)
                return
            if route == "/raw":
                self._raw((query.get("path") or [""])[0])
                return
            if route == "/api/text":
                try:
                    start = int((query.get("start") or ["0"])[0])
                    count = int((query.get("count") or [str(TEXT_INDEX_STEP)])[0])
                except (TypeError, ValueError):
                    start, count = 0, TEXT_INDEX_STEP
                self._text((query.get("path") or [""])[0], start, count)
                return
            if route == "/api/term/stream":
                self._term_stream(query)
                return
            if route == "/api/term/cwd":
                self._term_cwd(query)
                return
            self._error("未知路径", 404)

        def _asset(self, name):
            if name not in ("xterm.js", "xterm.css", "3dmol-min.js", "app.js", "app.css", "viewer.js"):
                self._error("资源不存在", 404)
                return
            path = ASSET_DIR / name
            if not path.is_file():
                self._error("资源缺失", 404)
                return
            content_type = "text/javascript; charset=utf-8" if name.endswith(".js") else "text/css; charset=utf-8"
            self._send(path.read_bytes(), content_type)

        def _info(self):
            remote = _CONF.get("remote_fs")
            info = {
                "root": str(self._root_dir()),
                "user": remote.spec["user"] if remote else _CONF["user"],
                "version": __version__,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "terminal": bool(remote) or _HAS_PTY,
                "remote": bool(remote),
            }
            if remote:
                info.update({
                    "remoteHost": remote.display,
                    "remoteRoot": remote.root,
                    "cacheRoot": str(remote.cache_root),
                    "auth": remote.auth,
                })
            self._json(info)

        def _list(self, rel):
            remote = _CONF.get("remote_fs")
            if remote is not None:
                try:
                    listed = remote.list_entries(rel)
                except RemoteError as exc:
                    self._handle_error(exc, 403)
                    return
                except OSError as exc:
                    self._error("无法读取远程目录：%s" % exc, 500)
                    return
                rows = []
                for item in listed:
                    child = Path(item["name"])
                    kind = "dir" if item["dir"] else _kind(child)
                    rows.append((not item["dir"], item["name"].lower(), {
                        "name": item["name"],
                        "path": item["path"],
                        "dir": item["dir"],
                        "kind": kind,
                        "mediaType": ("audio" if child.suffix.lower() in AUDIO_EXTS else "video")
                            if kind == "media" else None,
                        "size": item["size"],
                        "mtime": item["mtime"],
                        "ts": item["ts"],
                    }))
                rows.sort(key=lambda row: (row[0], row[1]))
                self._json({
                    "root": str(self._root_dir()),
                    "path": remote.current_remote(rel),
                    "parent": remote.parent_remote(rel),
                    "entries": [row[2] for row in rows],
                })
                return
            try:
                target = self._resolve(rel)
            except ValueError as exc:
                self._handle_error(exc, 403)
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
            remote = _CONF.get("remote_fs")
            suffix = Path(str(rel).replace("\\", "/")).suffix.lower()
            # 远程音视频：只读取远端 stat，绝不触发整文件下载。
            if remote is not None and suffix in MEDIA_EXTS:
                remote_path = remote.remote_for(rel)
                try:
                    info = remote.stat_remote(remote_path)
                    if not stat.S_ISREG(info.st_mode):
                        self._error("文件不存在", 404)
                        return
                except RemoteError as exc:
                    self._handle_error(exc, 403)
                    return
                except OSError as exc:
                    self._error("无法读取远程文件：%s" % exc, 500)
                    return
                self._json({
                    "path": remote.rel(remote_path),
                    "name": posixpath.basename(remote_path),
                    "size": int(info.st_size),
                    "mtime": time.strftime("%Y-%m-%d %H:%M",
                                           time.localtime(getattr(info, "st_mtime", 0) or 0)),
                    "kind": "media",
                    "mediaType": "audio" if suffix in AUDIO_EXTS else "video",
                    "url": "/raw?path=" + quote(remote_path),
                })
                return
            # 远程大文件不先整篇下载：文本按行分段加载（含 OUTCAR 等结构的“打开文本”），
            # 二进制等用户点下载再取；3D 解析仍走 /api/structure 的渲染通道。
            if (remote is not None
                    and suffix not in (IMAGE_EXTS | PDF_EXTS | MEDIA_EXTS)):
                remote_path = remote.remote_for(rel)
                try:
                    info = remote.stat_remote(remote_path)
                    if not stat.S_ISREG(info.st_mode):
                        self._error("文件不存在", 404)
                        return
                    rsize = int(info.st_size)
                    if rsize > LARGE_TEXT_BYTES:
                        ts = int(getattr(info, "st_mtime", 0) or 0)
                        opener = lambda: remote.open_remote(remote_path, size=rsize)
                        sample = b""
                        try:
                            sample = _sample_bytes(opener, rsize)
                        except Exception:  # noqa: BLE001 - 采样失败按二进制处理
                            sample = b""
                        base = {
                            "path": remote.rel(remote_path),
                            "name": posixpath.basename(remote_path),
                            "size": rsize,
                            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)),
                        }
                        if sample and _decode(sample) is not None:
                            index = _text_index(remote_path, opener, rsize, ts)
                            base.update({
                                "kind": "largeText",
                                "totalLines": index.total_lines,
                                "encoding": index.encoding,
                                "url": "/raw?path=" + quote(remote_path),
                            })
                        else:
                            base.update({
                                "kind": "binary",
                                "url": "/raw?path=" + quote(remote_path),
                            })
                        self._json(base)
                        return
                except RemoteError as exc:
                    self._handle_error(exc, 403)
                    return
                except OSError as exc:
                    self._error("无法读取远程文件：%s" % exc, 500)
                    return
            try:
                target = self._resolve(rel)
            except ValueError as exc:
                self._handle_error(exc, 403)
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
            if size > LARGE_TEXT_BYTES:
                opener = lambda: target.open("rb")
                sample = b""
                try:
                    sample = _sample_bytes(opener, size)
                except OSError:
                    sample = b""
                if sample and _decode(sample) is not None:
                    index = _text_index(str(target), opener, size, int(target.stat().st_mtime))
                    info.update({
                        "kind": "largeText",
                        "totalLines": index.total_lines,
                        "encoding": index.encoding,
                        "url": "/raw?path=" + quote(self._rel(target)),
                    })
                else:
                    info.update({"kind": "binary",
                                 "url": "/raw?path=" + quote(self._rel(target))})
                self._json(info)
                return

            data = target.read_bytes()
            text = _decode(data)
            if text is None:
                info.update({"kind": "binary", "url": "/raw?path=" + quote(self._rel(target))})
            else:
                info.update({"kind": "text", "text": text})
            self._json(info)

        def _text(self, rel, start, count):
            """按行返回大文本窗口；远程文件走 SFTP 流式读取，不下载整篇。"""
            remote = _CONF.get("remote_fs")
            try:
                if remote is not None:
                    remote_path = remote.remote_for(rel)
                    info = remote.stat_remote(remote_path)
                    if not stat.S_ISREG(info.st_mode):
                        self._error("文件不存在", 404)
                        return
                    size = int(info.st_size)
                    ts = int(getattr(info, "st_mtime", 0) or 0)
                    opener = lambda: remote.open_remote(remote_path, size=size)
                    key = remote_path
                    path_value = remote.rel(remote_path)
                    name_value = posixpath.basename(remote_path)
                    mtime_value = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
                else:
                    target = self._resolve(rel)
                    if not target.is_file():
                        self._error("文件不存在", 404)
                        return
                    st = target.stat()
                    size, ts = st.st_size, int(st.st_mtime)
                    opener = lambda: target.open("rb")
                    key = str(target)
                    path_value = self._rel(target)
                    name_value = target.name
                    mtime_value = _mtime(target)
                index = _text_index(key, opener, size, ts)
                start, lines = _text_lines(index, opener, start, count)
                self._json({
                    "path": path_value,
                    "name": name_value,
                    "size": size,
                    "mtime": mtime_value,
                    "encoding": index.encoding,
                    "totalLines": index.total_lines,
                    "start": start,
                    "lines": lines,
                })
            except (RemoteNotFound, ValueError) as exc:
                err = ValueError(str(exc))
                err.not_found = isinstance(exc, RemoteNotFound) or getattr(exc, "not_found", False)
                self._handle_error(err, 404 if err.not_found else 403)
            except RemoteError as exc:
                self._handle_error(exc, 403)
            except OSError as exc:
                self._error("无法读取文件：%s" % exc, 500)

        def _structure_remote(self, rel, frames=False, limit=0):
            """尝试走远端渲染通道；返回 True 表示响应已发出，False 表示回退本地。"""
            remote = _CONF.get("remote_fs")
            if remote is None:
                return False
            channel = _CONF.get("remote_render")
            if not remote.render_channel_ready(channel):
                # 负缓存到期后按需重试，避免服务启动失败后永远不再尝试。
                channel = remote.start_render_channel()
                _CONF["remote_render"] = channel
            if channel is None or not getattr(channel, "ready", False):
                reason = getattr(remote, "_render_error", "") or "channel-unavailable"
                remote_log("remote_render", host=remote.display,
                           result="fallback", reason="channel-unavailable", detail=reason)
                if "负缓存" not in reason:
                    print("[remote] 远端渲染通道不可用（%s），回退到本地解析" % reason,
                          file=sys.stderr, flush=True)
                return False
            remote_path = remote.remote_for(rel)
            try:
                info = remote.stat_remote(remote_path)
                size = int(getattr(info, "st_size", 0) or 0)
                mtime = int(getattr(info, "st_mtime", 0) or 0)
            except Exception as exc:  # noqa: BLE001 - stat 失败直接回退
                remote_log("remote_render", host=remote.display, file=remote_path,
                           result="fallback", reason="stat-failed", detail=str(exc)[:120])
                return False
            if not stat.S_ISREG(getattr(info, "st_mode", 0)) or size < REMOTE_RENDER_MIN_BYTES:
                return False
            if not _is_render_structure(remote_path):
                return False
            density = _is_vasp_density(Path(remote_path))
            size_limit = MAX_DENSITY_BYTES if density else MAX_STRUCT_BYTES
            if size > size_limit:
                label = "密度" if density else "结构"
                self._error("%s文件过大（上限 %d MB）" % (
                    label, size_limit // 1024 // 1024), 413)
                return True

            host = remote.spec["display"]
            cached = _render_cache_load(
                remote_path, mtime, size, frames, limit, host)
            if cached is not None:
                body_path, content_type, encoding, raw_size = cached
                if self._send_cached_render(
                        body_path, content_type, encoding, raw_size):
                    remote_log("remote_render", host=remote.display, file=remote_path,
                               size=size, result="cache-hit", bytes=raw_size,
                               encoding=encoding or "identity")
                    return True
                # Content-Length 无法可靠确定（如 meta 损坏）：删除坏条目，
                # 继续走远端重新生成，避免把压缩大小误当解压大小发给浏览器。
                _invalidate_render_cache(remote_path, host)
                remote_log("remote_render", host=remote.display, file=remote_path,
                           result="cache-corrupt", reason="bad-raw-size")

            sem = _render_semaphore(remote.spec["display"])
            if not sem.acquire(timeout=2):
                retry = max(1, min(10, int(REMOTE_RENDER_TOTAL_SECONDS) // 10))
                remote_log("remote_render", host=remote.display, file=remote_path,
                           result="busy-429", retry_after=retry)
                self._json({"error": "远端渲染队列已满，请稍后重试",
                            "retry_after": retry}, 429,
                           headers=[("Retry-After", str(retry))])
                return True
            started = time.monotonic()
            conn = None
            headers_sent = False
            tmp = None
            stage = "connect"
            try:
                target = "/api/structure?path=" + quote(remote_path, safe="/")
                if frames:
                    target += "&frames=1"
                    if limit:
                        target += "&limit=%d" % limit
                conn = http.client.HTTPConnection("127.0.0.1", channel.port,
                                                  timeout=REMOTE_RENDER_TIMEOUT)
                conn.request("GET", target, headers={"Connection": "close"})
                resp = conn.getresponse()
                if resp.status != 200:
                    raise _RenderFileError(resp.status)
                stage = "stream"
                content_type = (resp.getheader("Content-Type")
                                or "application/json; charset=utf-8")
                length = resp.getheader("Content-Length")
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                if length:
                    self.send_header("Content-Length", length)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Connection", "close")
                self.end_headers()
                headers_sent = True
                self.close_connection = True

                _base, body_path, meta_path = _render_cache_entry(
                    remote_path, mtime, size, frames, limit, host)
                body_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = body_path.with_name(body_path.name + ".part")
                try:
                    expected = int(length) if length else 0
                except (TypeError, ValueError):
                    expected = 0
                use_gzip = expected >= RENDER_CACHE_COMPRESS_MIN if expected else True
                fh = (gzip.open(str(tmp), "wb", compresslevel=RENDER_CACHE_COMPRESS_LEVEL)
                      if use_gzip else tmp.open("wb"))
                written = 0
                with fh:
                    while True:
                        if time.monotonic() - started > REMOTE_RENDER_TOTAL_SECONDS:
                            raise _RenderTimeoutError(
                                "渲染总时长超过 %d 秒" % REMOTE_RENDER_TOTAL_SECONDS)
                        chunk = resp.read(64 * 1024)  # 流式转发，不整包读入内存
                        if not chunk:
                            break
                        fh.write(chunk)
                        written += len(chunk)
                        try:
                            self.wfile.write(chunk)
                        except OSError:
                            pass  # 浏览器断开：缓存仍保留，避免重复请求远端
                os.replace(str(tmp), str(body_path))
                tmp = None
                meta_path.write_text(
                    json.dumps({
                        "content_type": content_type,
                        "encoding": "gzip" if use_gzip else "",
                        "raw_size": written or expected,
                    }), encoding="utf-8")
                _render_cache_prune()
                remote_log("remote_render", host=remote.display, file=remote_path,
                           size=size, result="ok", bytes=written,
                           elapsed_ms=int((time.monotonic() - started) * 1000))
                return True
            except Exception as exc:  # noqa: BLE001 - 按错误来源分级处理
                detail = "%s: %s" % (type(exc).__name__, str(exc)[:120])
                if not headers_sent:
                    if isinstance(exc, (_RenderFileError, _RenderTimeoutError)):
                        # 单文件解析失败/整体超时只影响本次请求，不关闭共享隧道。
                        remote.mark_render_request_failure(detail)
                    else:
                        # 连接/隧道级错误才关闭隧道并进入短负缓存。
                        remote.mark_render_failure(detail)
                if headers_sent:
                    if isinstance(exc, (_RenderFileError, _RenderTimeoutError)):
                        remote.mark_render_request_failure(detail)
                    else:
                        # 隧道级断连即使响应头已发出也要关掉，下次请求重建。
                        remote.mark_render_failure(detail)
                    remote_log("remote_render", host=remote.display, file=remote_path,
                               result="stream-error", stage=stage, detail=str(exc)[:120])
                    return True  # 响应头已发出，只能结束本次响应
                remote_log("remote_render", host=remote.display, file=remote_path,
                           size=size, result="fallback", stage=stage,
                           reason=type(exc).__name__, detail=str(exc)[:120],
                           elapsed_ms=int((time.monotonic() - started) * 1000))
                print("[remote] 远端渲染失败，回退到本地解析", file=sys.stderr, flush=True)
                return False
            finally:
                if tmp is not None:
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                sem.release()

        def _structure(self, rel, frames=False, limit=0):
            # -R 模式的本地回退会经 ensure() 把整个远端文件下载到缓存；
            # 先用远端 stat 的大小挡掉超限文件，避免大文件下载完才报 413。
            remote = _CONF.get("remote_fs")
            if remote is not None:
                remote_path = remote.remote_for(rel)
                try:
                    rinfo = remote.stat_remote(remote_path)
                except Exception:  # noqa: BLE001 - stat 失败继续走原有路径
                    rinfo = None
                if rinfo is not None and stat.S_ISREG(getattr(rinfo, "st_mode", 0)):
                    rsize = int(getattr(rinfo, "st_size", 0) or 0)
                    density = _is_vasp_density(Path(remote_path))
                    limit = MAX_DENSITY_BYTES if density else MAX_STRUCT_BYTES
                    if rsize > limit:
                        label = "密度" if density else "结构"
                        self._error("%s文件过大（上限 %d MB）" % (
                            label, limit // 1024 // 1024), 413)
                        return
            try:
                target = self._resolve(rel)
            except ValueError as exc:
                self._handle_error(exc, 403)
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
                    write_seq = seq[:limit] if limit and limit < len(seq) else seq
                    ase_write(xyz_buf, write_seq, format="xyz")
                    payload["xyz"] = xyz_buf.getvalue()
                    if len(write_seq) < len(seq):
                        payload["partial"] = True
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

        def _edit_structure(self):
            """把 3D 浏览中的原子移动/删除/改元素/新增写回结构文件（单帧可编辑，多帧只调整样式）。

            前端记录的移动坐标恒为笛卡尔(Å)，新增坐标为晶格分数坐标；
            写回时先用 ASE 按原坐标模式保存，再把 POSCAR 还原为原文件的
            分数/笛卡尔表示与缩放因子，避免原始坐标格式被改写。
            """
            remote = _CONF.get("remote_fs")
            try:
                payload = self._body()
                rel = str(payload.get("path") or "")
                moves = payload.get("moves") or []
                deletions = payload.get("deletions") or []
                additions = payload.get("additions") or []
                elements = payload.get("elements") or []
                cell = payload.get("cell")
                scaled = bool(payload.get("scaled"))
                if not rel or not isinstance(moves, list) or not isinstance(deletions, list):
                    raise ValueError("缺少 path 或 moves/deletions 参数无效")
                if not isinstance(additions, list):
                    raise ValueError("additions 参数无效")
                if not isinstance(elements, list):
                    raise ValueError("elements 参数无效")
                target = self._resolve(rel)
                if not target.is_file():
                    raise ValueError("文件不存在")
                if not _is_structure(target):
                    raise ValueError("不是可识别的结构文件")
                dels = sorted({int(i) for i in deletions
                               if isinstance(i, (int, float)) and int(i) >= 0}, reverse=True)
                from ase import Atom
                from ase.io import write as ase_write
                frames = _read_frames(target, MAX_STRUCT_FRAMES + 1)
                if not frames:
                    raise ValueError("无法解析结构")
                many = len(frames) > 1
                # 保存原 POSCAR 的坐标表示，写回后据此还原（轨迹多帧不支持编辑）。
                vasp_info = _vasp_coord_info(str(target)) if not many else None
                if many:
                    # 多帧轨迹：原子序号按帧对应，删除对所有帧生效；移动不支持。
                    for atoms in frames:
                        for i in dels:
                            if i < len(atoms):
                                del atoms[i]
                    ase_write(str(target), frames)
                else:
                    atoms = frames[0]
                    if cell is not None:
                        try:
                            matrix = [[float(v) for v in row[:3]] for row in cell[:3]]
                            if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
                                raise ValueError("晶格矩阵必须是 3×3")
                            atoms.set_cell(matrix, scale_atoms=False)
                        except (TypeError, ValueError) as exc:
                            raise ValueError("cell 参数无效：%s" % exc)
                    # 元素替换先按前端原始序号执行，后续删除/插入导致的位移不影响目标原子。
                    for item in elements:
                        if not isinstance(item, dict):
                            continue
                        try:
                            i = int(item.get("index", -1))
                        except (TypeError, ValueError):
                            continue
                        symbol = str(item.get("elem") or item.get("symbol") or "").strip()
                        if not (0 <= i < len(atoms)) or not symbol:
                            continue
                        try:
                            symbols = atoms.get_chemical_symbols()
                            symbols[i] = symbol
                            atoms.set_chemical_symbols(symbols)
                        except Exception as exc:
                            print("[structure] 修改元素 %s 失败：%s" % (symbol, exc),
                                  file=sys.stderr, flush=True)
                    for mv in moves:
                        if not isinstance(mv, dict):
                            continue
                        i = int(mv.get("index", -1))
                        if not (0 <= i < len(atoms)):
                            continue
                        try:
                            pos = [float(mv.get("x", 0)), float(mv.get("y", 0)), float(mv.get("z", 0))]
                        except (TypeError, ValueError):
                            continue
                        # 前端 MC.atomEdits 保存的是笛卡尔坐标(Å)；若显式标记
                        # coord=frac（或旧版 scaled=true）则按晶格换算成笛卡尔。
                        frac_move = (str(mv.get("coord", "cart")).lower() == "frac") or scaled
                        if frac_move and atoms.cell.any():
                            # ASE 的 scaled_positions() 是笛卡尔→分数；分数→笛卡尔
                            # 必须用 cartesian_positions()，否则原子会挤在原点附近。
                            atoms.positions[i] = atoms.cell.cartesian_positions(pos)
                        else:
                            atoms.positions[i] = pos
                    for i in dels:
                        if i < len(atoms):
                            del atoms[i]
                    for item in additions:
                        if not isinstance(item, dict):
                            continue
                        symbol = str(item.get("elem") or "").strip()
                        if not symbol:
                            continue
                        try:
                            values = [float(item.get("fx", 0)), float(item.get("fy", 0)),
                                      float(item.get("fz", 0))]
                        except (TypeError, ValueError):
                            continue
                        # 前端新增原子记录的是分数坐标（coord:"frac"）；兼容旧版无 coord 字段。
                        coord = str(item.get("coord", "frac")).lower()
                        try:
                            if coord == "cart":
                                pos = values
                            elif atoms.cell.any():
                                # values 是晶格分数坐标；分数→笛卡尔用 cartesian_positions。
                                pos = atoms.cell.cartesian_positions(values)
                            else:
                                pos = values
                            # 插到同元素块末尾，保持元素计数与坐标顺序一致。
                            last = -1
                            for i, atom in enumerate(atoms):
                                if str(getattr(atom, "symbol", "")).strip() == symbol:
                                    last = i
                            _insert_atom(atoms, last + 1 if last >= 0 else len(atoms),
                                         Atom(symbol, position=pos))
                        except Exception as exc:
                            print("[structure] 新增原子 %s 失败：%s" % (symbol, exc),
                                  file=sys.stderr, flush=True)
                            continue
                    if vasp_info is not None:
                        # 按原坐标模式写出，避免笛卡尔/分数在还原时反复换算；
                        # sort=False 保持原子序号与前端编辑记录一致。
                        ase_write(str(target), atoms, format="vasp",
                                  direct=vasp_info["direct"], sort=False)
                    else:
                        ase_write(str(target), atoms)
                # ASE 写 POSCAR 固定用 scale=1；还原原文件的坐标表示。
                if vasp_info is not None:
                    _target_path = Path(str(target))
                    _text = _target_path.read_text(encoding="utf-8", errors="replace")
                    _target_path.write_text(
                        _restore_vasp_coord_format(
                            _text, vasp_info, [str(a.symbol) for a in atoms]), encoding="utf-8")
                if remote is not None:
                    data = target.read_bytes()
                    remote_path = remote.remote_for(rel)
                    remote.upload(remote_path, data)
                    _invalidate_render_cache(
                        remote_path, remote.spec["display"])
                    local = remote.local_for_remote(remote_path)
                    local.parent.mkdir(parents=True, exist_ok=True)
                    local.write_bytes(data)
                    path_value = remote.rel(remote_path)
                else:
                    path_value = self._rel(target)
            except ImportError:
                self._error("缺少 ase，无法修改结构", 500)
                return
            except (ValueError, RemoteError) as exc:
                self._handle_error(exc, 400)
                return
            except Exception as exc:
                self._error("修改结构失败：%s" % exc, 500)
                return
            self._json({"ok": True, "path": path_value, "frames": len(frames),
                        "moves": len(moves) if not many else 0, "deletions": len(dels),
                        "additions": len(additions) if not many else 0})

        def _raw(self, rel):
            remote = _CONF.get("remote_fs")
            suffix = Path(str(rel).replace("\\", "/")).suffix.lower()
            if remote is not None and suffix in MEDIA_EXTS:
                self._send_remote_media(remote, rel, suffix)
                return
            try:
                target = self._resolve(rel)
            except ValueError as exc:
                self._handle_error(exc, 403)
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
            remote = _CONF.get("remote_fs")
            cwd = term.cwd() if term else None
            if remote is not None:
                # SSH shell 返回远程绝对路径；页面按远程目录展示。
                self._json({"cwd": cwd, "base": remote.root})
                return
            self._json({"cwd": cwd, "base": str(self._root_dir())})

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
            elif route == "/api/upload":
                self._upload()
            elif route == "/api/download":
                self._download()
            elif route == "/api/structure/edit":
                self._edit_structure()
            elif route == "/api/term/input":
                self._term_input()
            elif route == "/api/term/resize":
                self._term_resize()
            else:
                self._error("未知路径", 404)

        def _save(self):
            """保存文本/3D 状态；远程模式通过独立 SFTP 直接覆盖远端文件。"""
            remote = _CONF.get("remote_fs")
            try:
                payload = self._body()
                rel = str(payload.get("path") or "")
                text = payload.get("text")
                if not rel or not isinstance(text, str):
                    raise ValueError("缺少 path 或 text")
                if remote is not None:
                    target_remote = remote.remote_for(rel)
                    try:
                        info = remote.stat_remote(target_remote)
                    except (OSError, RemoteNotFound) as exc:
                        if not _remote_missing(exc):
                            raise
                        parent = posixpath.dirname(target_remote) or "/"
                        if not stat.S_ISDIR(remote.stat_remote(parent).st_mode):
                            raise ValueError("上级目录不存在")
                    else:
                        if not stat.S_ISREG(info.st_mode):
                            raise ValueError("目标是目录")
                else:
                    target = self._resolve(rel)
                    if target.is_dir():
                        raise ValueError("目标是目录")
                    if not target.parent.is_dir():
                        raise ValueError("上级目录不存在")
            except (ValueError, RemoteError) as exc:
                self._handle_error(exc, 400)
                return
            except OSError as exc:
                self._error("无法读取远程文件：%s" % exc, 500)
                return

            data = text.encode("utf-8")
            try:
                if remote is not None:
                    remote.upload(target_remote, data)
                    local = remote.local_for_remote(target_remote)
                    local.parent.mkdir(parents=True, exist_ok=True)
                    local.write_bytes(data)
                    info = remote.stat_remote(target_remote)
                    size = int(getattr(info, "st_size", len(data)))
                    ts = int(getattr(info, "st_mtime", 0) or time.time())
                    path_value = remote.rel(target_remote)
                else:
                    target.write_text(text, encoding="utf-8")
                    path_value = self._rel(target)
                    size = target.stat().st_size
                    ts = int(target.stat().st_mtime)
                mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
            except (OSError, RemoteError) as exc:
                self._error("保存失败：%s" % exc, 500)
                return
            self._json({"ok": True, "path": path_value,
                        "size": size, "mtime": mtime})

        def _rename(self):
            if self._readonly_remote():
                return
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
                self._handle_error(exc, 400)
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
                remote = _CONF.get("remote_fs")
                if remote is not None:
                    try:
                        remote.remove(remote.remote_for(rel))
                    except (RemoteNotFound, ValueError) as exc:
                        err = ValueError(str(exc))
                        err.not_found = isinstance(exc, RemoteNotFound) or getattr(exc, "not_found", False)
                        raise err
                    except RemoteError as exc:
                        raise ValueError(str(exc))
                    self._json({"ok": True})
                    return
                target = self._resolve(rel)
                if not target.exists():
                    raise ValueError("路径不存在")
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            except ValueError as exc:
                self._handle_error(exc, 400)
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
                remote = _CONF.get("remote_fs")
                if remote is not None:
                    folder_remote = remote.remote_for(rel)
                    if not stat.S_ISDIR(remote.stat_remote(folder_remote).st_mode):
                        raise ValueError("目录不存在")
                    target_remote = posixpath.normpath(posixpath.join(folder_remote, name))
                    try:
                        remote.stat_remote(target_remote)
                    except (OSError, RemoteNotFound) as exc:
                        if not _remote_missing(exc):
                            raise
                    else:
                        raise ValueError("同名文件已存在")
                else:
                    folder = self._resolve(rel)
                    if not folder.is_dir():
                        raise ValueError("目录不存在")
                    target = folder / name
                    if target.exists():
                        raise ValueError("同名文件已存在")
            except ValueError as exc:
                self._handle_error(exc, 400)
                return
            try:
                if remote is not None:
                    data = text.encode("utf-8")
                    remote.upload(target_remote, data)
                    local = remote.local_for_remote(target_remote)
                    local.parent.mkdir(parents=True, exist_ok=True)
                    local.write_bytes(data)
                    info = remote.stat_remote(target_remote)
                    size = int(getattr(info, "st_size", len(data)))
                    ts = int(getattr(info, "st_mtime", 0) or time.time())
                    path_value = remote.rel(target_remote)
                    name_value = posixpath.basename(target_remote)
                else:
                    target.write_text(text, encoding="utf-8")
                    path_value = self._rel(target)
                    name_value = target.name
                    size = target.stat().st_size
                    ts = int(target.stat().st_mtime)
                mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
            except (OSError, RemoteError) as exc:
                self._error("创建失败：%s" % exc, 500)
                return
            self._json({"ok": True, "path": path_value, "name": name_value,
                        "size": size, "mtime": mtime})

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
                remote = _CONF.get("remote_fs")
                if remote is not None:
                    folder_remote = remote.remote_for(rel)
                    if not stat.S_ISDIR(remote.stat_remote(folder_remote).st_mode):
                        raise ValueError("目录不存在")
                    target_remote = posixpath.normpath(posixpath.join(folder_remote, name))
                    try:
                        remote.stat_remote(target_remote)
                    except (OSError, RemoteNotFound) as exc:
                        if not _remote_missing(exc):
                            raise
                    else:
                        raise ValueError("同名项已存在")
                else:
                    folder = self._resolve(rel)
                    if not folder.is_dir():
                        raise ValueError("目录不存在")
                    target = folder / name
                    if target.exists():
                        raise ValueError("同名项已存在")
            except ValueError as exc:
                self._handle_error(exc, 400)
                return
            try:
                if remote is not None:
                    remote.makedirs(target_remote)
                    remote.local_for_remote(target_remote).mkdir(parents=True, exist_ok=True)
                    path_value = remote.rel(target_remote)
                    name_value = posixpath.basename(target_remote)
                else:
                    target.mkdir()
                    path_value = self._rel(target)
                    name_value = target.name
            except (OSError, RemoteError) as exc:
                self._error("创建失败：%s" % exc, 500)
                return
            self._json({"ok": True, "path": path_value, "name": name_value})

        def _upload(self):
            """接收拖入的本地文件/目录：远程走独立 SFTP，本地直接写盘。"""
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length < 0 or length > 256 * 1024 * 1024:
                    raise ValueError("文件过大（单个文件上限 256 MB）")
                folder_rel = unquote(self.headers.get("X-Upload-Dir") or "")
                if not folder_rel and _CONF.get("remote_fs") is None:
                    # 本地模式沿用旧回退；远程模式下 start 是本地缓存路径，
                    # 不能当作远端路径解析，空值直接表示远端运行根目录。
                    folder_rel = _CONF.get("start") or ""
                rel = unquote(self.headers.get("X-File-Path") or "")
                kind = self.headers.get("X-File-Kind") or "file"
                parts = [p for p in rel.replace("\\", "/").split("/") if p]
                if not parts or any(p in (".", "..") or "\x00" in p or "/" in p or "\\" in p for p in parts):
                    raise ValueError("上传路径不合法")
                folder = self._resolve(folder_rel)
                if not folder.is_dir():
                    raise ValueError("目标目录不存在")
                body = self.rfile.read(length) if length else b""
            except ValueError as exc:
                self._handle_error(exc, 400)
                return
            except OSError as exc:
                self._error("读取上传内容失败：%s" % exc, 500)
                return

            remote = _CONF.get("remote_fs")
            try:
                if remote is not None:
                    base_remote = remote.remote_for_local(folder)
                    target_remote = posixpath.normpath(posixpath.join(base_remote, *parts))
                    if kind == "dir":
                        remote.makedirs(target_remote)
                    else:
                        remote.upload(target_remote, body)
                        local = remote.local_for_remote(target_remote)
                        local.parent.mkdir(parents=True, exist_ok=True)
                        local.write_bytes(body)
                    rel_path = remote.rel(target_remote)
                    size = len(body)
                    mtime = time.strftime("%Y-%m-%d %H:%M")
                else:
                    import os as _os
                    target = folder.joinpath(*parts).resolve()
                    # _resolve 已校验 folder；这里再确认最终路径没有逃出允许范围。
                    try:
                        self._resolve(_os.path.relpath(target, self._root_dir()))
                    except ValueError:
                        raise ValueError("上传目标超出允许目录")
                    if kind == "dir":
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(body)
                    rel_path = self._rel(target)
                    size = len(body)
                    mtime = _mtime(target)
            except (ValueError, RemoteError) as exc:
                self._handle_error(exc, 400)
                return
            except OSError as exc:
                self._error("上传失败：%s" % exc, 500)
                return
            self._json({"ok": True, "path": rel_path, "size": size, "mtime": mtime})

        def _download(self):
            """批量下载：把选中的文件或目录递归打成 ZIP 返回。"""
            try:
                payload = self._body()
                paths = payload.get("paths")
                if not isinstance(paths, list) or not paths:
                    raise ValueError("缺少要下载的文件")
                if len(paths) > 500:
                    raise ValueError("一次最多下载 500 个文件")
            except ValueError as exc:
                self._handle_error(exc, 400)
                return

            buf = io.BytesIO()
            used = {}
            state = {"count": 0}

            def arc_name(name):
                name = (name or "file").replace("\\", "/").lstrip("/") or "file"
                used[name] = used.get(name, 0) + 1
                if used[name] == 1:
                    return name
                stem, dot, suffix = name.rpartition(".")
                base = stem if dot and stem else name
                return "%s-%d%s" % (base, used[name], ("." + suffix) if dot else "")

            def add_remote_tree(zf, remote, remote_path, prefix, depth):
                if state["count"] >= 500 or depth > 32:
                    return
                info = remote.stat_remote(remote_path)
                if stat.S_ISDIR(info.st_mode):
                    base = posixpath.basename(posixpath.normpath(remote_path)) or "dir"
                    folder = posixpath.join(prefix, base) if prefix else base
                    for row in remote.list_entries(remote_path):
                        child = row["path"]
                        if row.get("dir"):
                            add_remote_tree(zf, remote, child, folder, depth + 1)
                        elif state["count"] < 500:
                            name = posixpath.join(folder, row["name"])
                            # 已预览/编辑过的文件直接复用本地缓存，避免重复 SFTP 下载。
                            local = remote.ensure(child)
                            zf.write(str(local), arc_name(name))
                            state["count"] += 1
                elif stat.S_ISREG(info.st_mode):
                    name = posixpath.basename(posixpath.normpath(remote_path)) or "file"
                    local = remote.ensure_stat(remote_path, info)
                    zf.write(str(local), arc_name(posixpath.join(prefix, name) if prefix else name))
                    state["count"] += 1

            remote = _CONF.get("remote_fs")
            try:
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for item in paths:
                        if remote is not None:
                            add_remote_tree(zf, remote, remote.remote_for(str(item)), "", 0)
                            continue
                        target = self._resolve(str(item))
                        if target.is_dir():
                            base = target.name or "dir"
                            for child in sorted(target.rglob("*")):
                                if state["count"] >= 500:
                                    break
                                if not child.is_file():
                                    continue
                                try:
                                    child.resolve().relative_to(target.resolve())
                                except ValueError:
                                    continue
                                rel = child.relative_to(target).as_posix()
                                zf.write(str(child), arc_name(posixpath.join(base, rel)))
                                state["count"] += 1
                        elif target.is_file():
                            zf.write(str(target), arc_name(target.name or "file"))
                            state["count"] += 1
            except (ValueError, OSError, RemoteError) as exc:
                self._error("打包失败：%s" % exc, 500)
                return
            if not state["count"]:
                self._error("没有可下载的文件", 400)
                return
            self._send(buf.getvalue(), "application/zip", headers=[
                ("Content-Disposition", 'attachment; filename="mcta-download.zip"')])

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


# ------------------------------------------------------------------ 启动 ---
class _UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """只监听 Unix socket 的 HTTP 服务：socket 0700 目录 + 0600 文件。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, path, handler):
        path = str(Path(path).expanduser())
        self._socket_path = os.path.abspath(path)
        parent = os.path.dirname(self._socket_path)
        os.makedirs(parent, mode=0o700, exist_ok=True)
        # 默认目录是专用目录，直接收紧权限；自定义路径只保证新建目录为 0700。
        default_dir = str((Path.home() / ".config" / "mcta" / "sock").resolve())
        if parent == default_dir:
            os.chmod(parent, 0o700)
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)
        super().__init__(self._socket_path, handler)
        os.chmod(self._socket_path, 0o600)
        # BaseHTTPRequestHandler 会读取这两个属性；Unix socket 没有 TCP 地址。
        self.server_name = "localhost"
        self.server_port = 0

    def get_request(self):
        conn, _addr = super().get_request()
        return conn, ("unix", 0)

    def unlink_socket(self):
        try:
            os.unlink(self._socket_path)
        except FileNotFoundError:
            pass

    def server_close(self):
        super().server_close()
        self.unlink_socket()


class _Server(ThreadingHTTPServer):
    """按监听地址自动选择 IPv4 / IPv6。"""

    def __init__(self, host, port, handler):
        try:
            family = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][0]
        except socket.gaierror:
            family = socket.AF_INET
        self.address_family = family
        super().__init__((host, port), handler)

    def handle_error(self, request, client_address):
        """未捕获异常只留一行摘要；完整堆栈写入 -o 日志，终端不刷 traceback。"""
        try:
            import traceback
            import mcta.server as _srv
            etype, exc, tb = sys.exc_info()
            summary = "%s: %s" % (etype.__name__ if etype else "Exception", exc)
            print("[mt.server] 请求处理异常 %s: %s" % (client_address[0], summary),
                  file=sys.stderr, flush=True)
            path = getattr(_srv, "_LOG_PATH", None)
            if path:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write("[%s] 请求处理异常 %s\n" % (
                        time.strftime("%Y-%m-%d %H:%M:%S"), client_address))
                    traceback.print_exception(etype, exc, tb, file=fh)
        except Exception:
            pass
