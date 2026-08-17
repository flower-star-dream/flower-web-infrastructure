"""
数据库会话生命周期管理 Mixin

@Author: 花海
@Date: 2026/08/14 22:30
@Description: 会话生命周期管理（框架底层处理，业务无需手写 try/finally）：
              `async with factory.session() as session:` 进入自动创建会话，
              退出自动提交（异常自动回滚）并关闭，释放连接。业务代码只写业务逻辑。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from web_infra.db.database_session_interface import DatabaseSessionInterface


class SessionScopeMixin(ABC):
    """会话生命周期管理 Mixin（提供 session() 异步上下文管理器）"""

    @abstractmethod
    async def create_session(self) -> DatabaseSessionInterface:
        """创建通用会话（由子类实现）"""

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[DatabaseSessionInterface, None]:
        """进入创建会话，退出自动提交（异常回滚）并关闭。

        用法（业务无需 try/finally）：
            async with db.session() as session:
                rows = await session.query_all(sql, params)
        """
        session = await self.create_session()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
