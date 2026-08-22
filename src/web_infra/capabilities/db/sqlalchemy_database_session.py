"""
SQLAlchemy 通用数据库会话适配

@Author: 花海
@Date: 2026/08/14 10:00
@Description: SQLAlchemy AsyncSession 的通用 DatabaseSessionInterface 适配，
              将 SQLAlchemy 原生 API 包装为通用数据库会话接口，屏蔽驱动差异。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 仅静态检查使用，运行时跳过（延迟导入，最小安装不含 SQLAlchemy 时 import 本模块不失败）
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

from web_infra.capabilities.db.database_session_interface import DatabaseSessionInterface


class SqlAlchemyDatabaseSession(DatabaseSessionInterface):
    """SQLAlchemy AsyncSession 的通用 DatabaseSessionInterface 适配"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, sql: str, params: Any = None) -> int:
        from sqlalchemy import text

        result = await self._session.execute(text(sql), params or {})
        # Result 基类无 rowcount（DML 实际返回 CursorResult 才暴露），用 getattr 兼容类型与运行时
        return getattr(result, "rowcount", 0) or 0

    async def query_one(self, sql: str, params: Any = None) -> dict[str, Any] | None:
        from sqlalchemy import text

        result = await self._session.execute(text(sql), params or {})
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def query_all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        from sqlalchemy import text

        result = await self._session.execute(text(sql), params or {})
        return [dict(row) for row in result.mappings().all()]

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def close(self) -> None:
        await self._session.close()

    def native(self) -> AsyncSession:
        """返回底层 SQLAlchemy AsyncSession（供传播栈解包复用外层会话）"""
        return self._session
