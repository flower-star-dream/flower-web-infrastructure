"""
数据库会话生命周期封装单元测试

@Author: 花海
@Date: 2026/08/14 22:30
@Description: 验证 session() 上下文管理器自动管理生命周期：
              正常退出自动提交、异常自动回滚、会话始终关闭（业务无需手写 try/finally）。
"""
import pytest

from web_infra.capabilities.db import SqliteSessionFactory


@pytest.fixture()
def factory():
    """内存 sqlite 会话工厂"""
    f = SqliteSessionFactory(db_path=":memory:")
    f.create_session().execute("CREATE TABLE t_order (id INTEGER PRIMARY KEY, name TEXT)")
    yield f
    f.close()


@pytest.mark.asyncio
async def test_session_commits_on_success(factory):
    """正常退出自动提交：数据落库"""
    async with factory.session() as session:
        session.execute("INSERT INTO t_order (id, name) VALUES (1, 'a')")
    # 新会话可见（已提交）
    check = factory.create_session()
    rows = check.query_all("SELECT * FROM t_order")
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_session_rolls_back_on_error(factory):
    """异常自动回滚：数据不落库"""
    with pytest.raises(RuntimeError):
        async with factory.session() as session:
            session.execute("INSERT INTO t_order (id, name) VALUES (2, 'b')")
            raise RuntimeError("boom")
    check = factory.create_session()
    rows = check.query_all("SELECT * FROM t_order")
    assert rows == []  # 已回滚


class _FakeFactory:
    """模拟异步工厂：记录 commit/rollback/close 调用（验证 Mixin 生命周期）"""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.fail = False

    async def create_session(self) -> "_FakeSession":
        return _FakeSession(self)

    async def close(self) -> None:
        pass

    async def health_check(self) -> bool:
        return True


class _FakeSession:
    """模拟通用会话（DatabaseSessionInterface 语义）"""

    def __init__(self, factory: _FakeFactory) -> None:
        self.factory = factory

    async def commit(self) -> None:
        self.factory.events.append("commit")

    async def rollback(self) -> None:
        self.factory.events.append("rollback")

    async def close(self) -> None:
        self.factory.events.append("close")


@pytest.mark.asyncio
async def test_session_scope_commit_and_close():
    """Mixin：正常退出自动 commit + close（无异常不 rollback）"""
    from web_infra.capabilities.db import SessionScopeMixin

    class Factory(_FakeFactory, SessionScopeMixin):
        pass

    factory = Factory()
    async with factory.session():
        pass
    assert factory.events == ["commit", "close"]


@pytest.mark.asyncio
async def test_session_scope_rollback_and_close():
    """Mixin：异常自动 rollback + close"""
    from web_infra.capabilities.db import SessionScopeMixin

    class Factory(_FakeFactory, SessionScopeMixin):
        pass

    factory = Factory()
    with pytest.raises(RuntimeError):
        async with factory.session():
            raise RuntimeError("boom")
    assert factory.events == ["rollback", "close"]
