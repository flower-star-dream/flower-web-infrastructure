"""
数据库会话依赖注入

@Author: 花海
@Date: 2026/08/14 22:30
@Description: FastAPI 依赖注入封装：向路由注入已管理生命周期的数据库会话，
              业务函数内无需手写 try/finally 与 close（框架自动提交/回滚/关闭）。
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Callable

from web_infra.capabilities.db.database_session_interface import DatabaseSessionInterface


def provide_db_session(factory: Any) -> Callable[[], AsyncIterator[DatabaseSessionInterface]]:
    """构造 FastAPI 依赖：注入自动管理生命周期的数据库会话。

    用法：
        app = create_app()
        db = app.state.db
        @app.get("/orders")
        async def list_orders(session: DatabaseSessionInterface = Depends(provide_db_session(db))):
            return await session.query_all("SELECT * FROM t_order")
    """
    async def _dependency() -> AsyncIterator[DatabaseSessionInterface]:
        async with factory.session() as session:
            yield session

    return _dependency
