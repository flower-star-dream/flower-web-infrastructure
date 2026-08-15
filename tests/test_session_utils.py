"""
数据库会话工具单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证长耗时调用前释放连接持有的工具函数与上下文管理器。
"""
import pytest

from web_infra.db import connection_released, release_session_connection


class _FakeSession:
    """测试用会话桩：记录 commit/rollback 调用次数"""

    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


@pytest.mark.asyncio
async def test_release_none_session():
    """传入 None 时不执行任何操作"""
    await release_session_connection(None)


@pytest.mark.asyncio
async def test_release_commits_session():
    """正常释放：提交当前事务归还连接"""
    session = _FakeSession()
    await release_session_connection(session)
    assert session.committed == 1
    assert session.rolled_back == 0


@pytest.mark.asyncio
async def test_connection_released_context():
    """上下文管理器进入时释放连接"""
    session = _FakeSession()
    async with connection_released(session):
        pass
    assert session.committed == 1
