"""
SQLite 会话工厂

@Author: 花海
@Date: 2026/08/14 22:30
@Description: sqlite3 同步会话工厂参考实现（轻量/测试场景）。
              提供 session() 上下文管理器：进入创建会话，退出自动提交（异常回滚），业务无需 try/finally。
"""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from web_infra.db.database_config import DatabaseConfig
from web_infra.db.sqlite_session import SqliteSession


class SqliteSessionFactory:
    """sqlite3 同步会话工厂参考实现（轻量/测试场景）"""

    def __init__(self, config: DatabaseConfig | None = None, db_path: str = ":memory:") -> None:
        self.config = config or DatabaseConfig()
        self._db_path = self._parse_path(self.config.url) or db_path
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)

    @staticmethod
    def _parse_path(url: str) -> str:
        """解析 sqlite:///path 形式的连接地址"""
        if url.startswith("sqlite:///"):
            return url[len("sqlite:///"):]
        return url

    def create_session(self) -> SqliteSession:
        """创建同步会话"""
        return SqliteSession(self._conn)

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[SqliteSession, None]:
        """异步上下文管理器：进入创建会话，退出自动提交（异常回滚），业务无需 try/finally"""
        session = self.create_session()
        with session.transaction():
            yield session

    def close(self) -> None:
        """关闭底层连接"""
        self._conn.close()
