"""
数据库会话工具

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 长耗时外部调用（LLM 等）期间释放连接持有的工具函数与上下文管理器。
              在长耗时外部调用前结束当前事务归还连接，调用结束后 session 仍可继续执行 SQL。
"""
from __future__ import annotations

from typing import Any


async def release_session_connection(session: Any | None) -> None:
    """结束 session 当前事务并归还连接（长耗时外部调用前调用）。

    无活动事务时 commit 为 no-op；提交失败时先回滚再抛出原始异常。

    :param session: AsyncSession（或带 commit/rollback 的对象）；为 None 时直接返回
    :raises: 提交异常
    """
    if session is None:
        return
    try:
        await session.commit()
    except Exception as e:
        try:
            await session.rollback()
        except Exception:
            # 回滚失败说明会话状态已损坏，保留原始提交异常
            pass
        raise e


class connection_released:
    """async 上下文管理器：进入时释放一个或多个 session 的连接持有。

    用法示例：:

        async with connection_released(rag_session, llm_session):
            answer = await model.ainvoke(messages)  # 长耗时调用期间无连接持有
    """

    def __init__(self, *sessions: Any) -> None:
        self._sessions = sessions

    async def __aenter__(self) -> "connection_released":
        for session in self._sessions:
            await release_session_connection(session)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        return None
