"""
SQLite 会话工厂

@Author: 花海
@Date: 2026/08/14 22:30
@Description: sqlite3 同步会话工厂参考实现（轻量/测试场景）。
              提供 session() 上下文管理器：进入创建会话，退出自动提交（异常回滚），业务无需 try/finally。
              2026/08/22 扩展：支持事务传播（REQUIRED/REQUIRES_NEW/NESTED，原生 SAVEPOINT），
              隔离级别对 SQLite 静默忽略（SQLite 无事务隔离级别概念）。
"""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from web_infra.capabilities.db.database_config import DatabaseConfig
from web_infra.capabilities.db.sqlite_session import SqliteSession
from web_infra.capabilities.db.transaction_propagation import (
    Propagation,
    TransactionPropagationError,
    current_transaction,
    mark_rollback_only,
    pop_transaction,
    push_transaction,
)


class SqliteSessionFactory:
    """sqlite3 同步会话工厂参考实现（轻量/测试场景，支持事务传播）"""

    def __init__(self, config: DatabaseConfig | None = None, db_path: str = ":memory:") -> None:
        self.config = config or DatabaseConfig()
        self._db_path = self._parse_path(self.config.url) or db_path
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)

    @property
    def db_path(self) -> str:
        """数据库文件路径（供 SQLAlchemy 异步引擎复用同一数据文件；:memory: 为每连接独立内存库）"""
        return self._db_path

    @staticmethod
    def _parse_path(url: str) -> str:
        """解析 sqlite:///path 形式的连接地址"""
        if url.startswith("sqlite:///"):
            return url[len("sqlite:///"):]
        return url

    def create_session(self) -> SqliteSession:
        """创建同步会话"""
        return SqliteSession(self._conn)

    def _create_connection(self) -> sqlite3.Connection:
        """创建独立 sqlite3 连接（REQUIRES_NEW 传播用；:memory: 每连接独立内存库，数据不可见）"""
        return sqlite3.connect(self._db_path, check_same_thread=False)

    @asynccontextmanager
    async def session(
        self, propagation: Propagation = Propagation.REQUIRED
    ) -> AsyncGenerator[SqliteSession, None]:
        """异步上下文管理器（支持事务传播）：进入创建会话，退出自动提交（异常回滚）。

        传播语义：
        - REQUIRED（默认）：复用外层连接（同一事务，内层不提交/关闭）
        - REQUIRES_NEW：新建独立连接独立事务（:memory: 模式数据隔离，生产用文件库）
        - NESTED：外层连接内开启原生 SAVEPOINT，内层异常仅回滚保存点
        隔离级别：SQLite 无事务隔离级别概念，本实现静默忽略。
        """
        top = current_transaction()

        # REQUIRED：复用外层连接
        if top is not None and propagation is Propagation.REQUIRED:
            frame = push_transaction(top.session, owner=False)
            try:
                yield SqliteSession(top.session)
            except Exception:
                mark_rollback_only()
                raise
            finally:
                pop_transaction()
            return

        # NESTED：外层连接内 SAVEPOINT
        if top is not None and propagation is Propagation.NESTED:
            sp_name = f"sp_{id(top.session)}"
            top.session.execute(f"SAVEPOINT {sp_name}")
            frame = push_transaction(top.session, owner=False, savepoint=True, savepoint_tx=sp_name)
            try:
                yield SqliteSession(top.session)
            except Exception:
                top.session.execute(f"ROLLBACK TO {sp_name}")
                raise
            else:
                top.session.execute(f"RELEASE {sp_name}")
            finally:
                pop_transaction()
            return

        # 无外层（REQUIRED/NESTED 退化）或 REQUIRES_NEW：新建 owner 事务
        own_connection = top is not None and propagation is Propagation.REQUIRES_NEW
        conn = self._create_connection() if own_connection else self._conn
        frame = push_transaction(conn, owner=True)
        try:
            yield SqliteSession(conn)
            if frame.rollback_only:
                conn.rollback()
                raise TransactionPropagationError(
                    "事务传播冲突：内层事务失败，外层事务已标记 rollback-only，强制回滚"
                )
            conn.commit()
            from web_infra.capabilities.db.transaction_synchronization import trigger_after_commit_sync

            # SQLite 为同步参考实现：同步触发 after_commit（回调为 awaitable 时同步执行）
            trigger_after_commit_sync()
        except Exception:
            conn.rollback()
            raise
        finally:
            if own_connection:
                conn.close()
            pop_transaction()

    def close(self) -> None:
        """关闭底层连接"""
        self._conn.close()

    async def health_check(self) -> bool:
        """健康检查：SQLite 连接可用性探测（SELECT 1 失败视为不健康）"""
        try:
            with self._conn:
                self._conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False
