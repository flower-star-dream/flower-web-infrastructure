"""
SQLite 会话

@Author: 花海
@Date: 2026/08/14 10:00
@Description: sqlite3 同步会话参考实现（单体轻量/测试场景，非通用异步接口实现）。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Generator


class SqliteSession:
    """sqlite3 同步会话参考实现（单体轻量/测试场景，非通用异步接口实现）"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params: Any = None) -> int:
        """执行写操作，返回影响行数"""
        cursor = self._conn.execute(sql, params or ())
        return cursor.rowcount

    def query_one(self, sql: str, params: Any = None) -> dict[str, Any] | None:
        """查询单行"""
        cursor = self._conn.execute(sql, params or ())
        row = cursor.fetchone()
        return dict(row) if row is not None else None

    def query_all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        """查询多行"""
        cursor = self._conn.execute(sql, params or ())
        return [dict(row) for row in cursor.fetchall()]

    @contextmanager
    def transaction(self) -> Generator["SqliteSession", None, None]:
        """事务上下文：正常提交，异常回滚"""
        try:
            yield self
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
