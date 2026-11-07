"""状态层：检索与导出事件落 SQLite，中断可恢复、决策可回放。"""
import json
import sqlite3
import time
from contextlib import contextmanager

from mcta.seeker import config


@contextmanager
def _db():
    """打开连接、提交事务、**关闭连接**。

    注意 sqlite3.Connection 的 `with` 只负责事务（commit/rollback），
    并不关闭连接；早期版本直接 `with _conn() as c` 会让每个事件泄漏一个
    文件句柄，长会话下可能把 Windows 上的 db 文件锁住。
    """
    config.ensure_dirs()
    c = sqlite3.connect(config.DB_PATH)
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS events(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts TEXT, kind TEXT, payload TEXT, result TEXT)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS structures(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts TEXT, mp_id TEXT UNIQUE, formula TEXT,
                   export_dir TEXT, status TEXT, meta TEXT)"""
        )
        with c:                      # 事务边界
            yield c
    finally:
        c.close()


def log_event(kind: str, payload: dict, result=None) -> None:
    with _db() as c:
        c.execute(
            "INSERT INTO events(ts,kind,payload,result) VALUES (?,?,?,?)",
            (time.strftime("%Y-%m-%d %H:%M:%S"), kind,
             json.dumps(payload, ensure_ascii=False, default=str),
             json.dumps(result, ensure_ascii=False, default=str)),
        )


def register_structure(mp_id: str, formula: str, export_dir: str,
                       status: str = "exported", meta: dict = None) -> None:
    with _db() as c:
        c.execute(
            "INSERT OR REPLACE INTO structures(ts,mp_id,formula,export_dir,status,meta)"
            " VALUES (?,?,?,?,?,?)",
            (time.strftime("%Y-%m-%d %H:%M:%S"), mp_id, formula, export_dir,
             status, json.dumps(meta or {}, ensure_ascii=False, default=str)),
        )


def count_structures() -> int:
    with _db() as c:
        return c.execute("SELECT COUNT(*) FROM structures").fetchone()[0]


def tail_events(n: int = 20) -> list:
    with _db() as c:
        rows = c.execute(
            "SELECT ts,kind,payload,result FROM events ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [{"ts": r[0], "kind": r[1],
             "payload": json.loads(r[2]), "result": json.loads(r[3])} for r in rows]
