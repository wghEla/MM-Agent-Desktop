"""SQLite 数据库层：连接管理、WAL、迁移、事务。

并发约定（v0.1）：单进程内由 threading.Lock 串行化写事务；跨进程互斥由
workspace 的 run.lock + 单运行锁语义负责（v0.2 强化 Windows 细节）。
"""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from mmagent.state.schema_v1 import SCHEMA_V1

_MIGRATIONS: list[tuple[int, str]] = [
    (1, SCHEMA_V1),
]


class Database:
    """项目库（.mmagent/project.db）的薄封装。线程安全（写锁串行）。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=FULL")

    # ------------------------------------------------------------- 迁移
    def migrate(self) -> int:
        """应用未执行的迁移，返回应用数量。"""
        with self._lock, self.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
            )
            applied = {
                r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            count = 0
            for version, sql in _MIGRATIONS:
                if version in applied:
                    continue
                conn.executescript(sql)
                conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
                count += 1
            return count

    @property
    def user_version(self) -> int:
        (v,) = self._conn.execute("PRAGMA user_version").fetchone()
        return int(v)

    # ------------------------------------------------------------- 事务
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE 写事务；异常回滚。"""
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        """单条写语句（自带事务）。"""
        with self.transaction() as conn:
            return conn.execute(sql, params)

    def query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
