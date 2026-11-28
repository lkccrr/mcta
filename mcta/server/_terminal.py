"""终端（PTY）与运行期配置。

mt.server 从 mcta/server/__init__.py 拆出：xterm.js 后端使用的 PTY shell、
会话订阅/回放、token 与环境变量常量、全局运行配置 _CONF。
HTTP 侧由 _handlers.py 使用，进程入口由 __init__.py 使用。
"""

import getpass
import os
import queue
import secrets
import signal
import threading
from pathlib import Path

try:  # 终端只在 POSIX 上可用
    import fcntl
    import pty
    import select
    import struct
    import termios
    _HAS_PTY = True
except ImportError:  # pragma: no cover - Windows
    _HAS_PTY = False

TOKEN_COOKIE = "mcta_token"


TOKEN_ENV = "MCTA_SERVER_TOKEN"


NO_TOKEN_ENV = "MCTA_SERVER_NO_TOKEN"


ROOT_ENV = "MCTA_SERVER_ROOT"


GUARD_ENV = "MCTA_SERVER_GUARD_PID"


SKIP_CONFIRM_ENV = "MCTA_SERVER_NO_CONFIRM"


NOHUP_ENV = "MCTA_SERVER_NOHUP"


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
                # 登录 shell：与 SSH/普通登录终端一致，读取 /etc/profile 与 ~/.profile，
                # 避免网页终端的 $PATH 与通常 shell 不一致。
                os.execvpe(shell, [shell, "-l", "-i"], env)
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
    sid = _clean_sid(sid)
    remote = _CONF.get("remote_ssh")
    if remote is None and not _HAS_PTY:
        return None
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
        if remote is not None:
            from ._remote import _RemoteTerminal
            term = _RemoteTerminal(remote, rows, cols)
        else:
            start = Path(_CONF["start"]).resolve()
            term = _Terminal(str(start), rows, cols)
        _TERMINALS[sid] = term
        return term
