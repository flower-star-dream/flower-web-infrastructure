"""
声明式事务 @transactional 单元测试

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 验证 @transactional 作为声明式事务装饰器——事务边界复用现有事务传播栈
              （SessionScopeMixin.session 传播 + current_session），方法内直接用 current_session()
              取会话执行 SQL；成功退出统一 commit、异常整体回滚；
              并用真实 SqliteSessionFactory（文件库）补充集成用例，验证提交落库、异常回滚不落库。
"""
import pytest

from web_infra.capabilities.db import SessionScopeMixin, Propagation, SqliteSessionFactory
from web_infra.capabilities.db.transaction_propagation import current_session
from web_infra.capabilities.db.transactional import transactional as _dec
from web_infra.core.aop import bind_components


class _FakeFac:
    """模拟会话工厂：记录 commit/rollback/close 事件与业务写入 SQL"""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.data: list[str] = []

    async def create_session(self) -> "_FakeSession":
        """创建模拟会话"""
        return _FakeSession(self)


class _FakeSession:
    """模拟异步会话：commit/rollback/close/execute 均为异步"""

    def __init__(self, fac: _FakeFac) -> None:
        self.fac = fac

    async def commit(self) -> None:
        """提交：记录事件"""
        self.fac.events.append("commit")

    async def rollback(self) -> None:
        """回滚：记录事件"""
        self.fac.events.append("rollback")

    async def close(self) -> None:
        """关闭：记录事件"""
        self.fac.events.append("close")

    async def execute(self, sql: str, params: object = None) -> None:
        """执行 SQL：记录业务写入"""
        self.fac.data.append(sql)


class _FakeDb(SessionScopeMixin):
    """模拟 db 组件：继承 SessionScopeMixin 复用 session() 上下文管理器（支持事务传播）"""

    def __init__(self, fac: _FakeFac) -> None:
        self.fac = fac

    async def create_session(self) -> _FakeSession:
        """创建模拟会话"""
        return await self.fac.create_session()


@pytest.mark.asyncio
async def test_transactional_commits_on_success() -> None:
    """成功路径：绑定 db 组件后，@transactional 方法退出统一 commit，不 rollback"""
    fac = _FakeFac()
    bind_components({"db": _FakeDb(fac)})

    @_dec()
    async def create_order() -> str:
        s = current_session()
        await s.execute("INSERT INTO t_order ...")
        return "ok"

    result = await create_order()
    assert result == "ok"
    assert "commit" in fac.events
    assert "rollback" not in fac.events


@pytest.mark.asyncio
async def test_transactional_rolls_back_on_error() -> None:
    """异常路径：@transactional 方法抛异常时整体 rollback，不 commit"""
    fac = _FakeFac()
    bind_components({"db": _FakeDb(fac)})

    @_dec()
    async def create_order() -> str:
        s = current_session()
        await s.execute("INSERT INTO t_order ...")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await create_order()
    assert "rollback" in fac.events
    assert "commit" not in fac.events


@pytest.mark.asyncio
async def test_transactional_without_db_component_raises() -> None:
    """db 组件不可得时：@transactional 立即失败，给出可读错误。

    显式绑定空组件字典（等价于未装配 db），规避框架 bind_components 的 ContextVar
    在测试会话间泄漏导致的前序绑定残留，保证用例确定性。
    """
    bind_components({})

    @_dec()
    async def create_order() -> str:
        s = current_session()
        await s.execute("INSERT INTO t_order ...")
        return "ok"

    with pytest.raises(RuntimeError, match="取不到 db 组件"):
        await create_order()


@pytest.mark.asyncio
async def test_transactional_with_sqlite_factory(tmp_path) -> None:
    """真实 SqliteSessionFactory：@transactional 事务提交后数据落库；异常回滚不落库"""
    fac = SqliteSessionFactory(db_path=str(tmp_path / "tx.db"))
    fac.create_session().execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")

    class _Fac:
        """将 SqliteSessionFactory.session() 透传给框架 db 组件接口（SQLite 无隔离级别，仅透传传播级别）"""

        def session(self, propagation: Propagation = Propagation.REQUIRED, isolation_level: str | None = None):
            return fac.session(propagation=propagation)

    bind_components({"db": _Fac()})

    @_dec()
    async def create_ok() -> int:
        s = current_session()
        s.execute("INSERT INTO t (id, name) VALUES (1, 'a')")
        return 1

    assert await create_ok() == 1
    rows = fac.create_session().query_all("SELECT name FROM t")
    assert rows == [{"name": "a"}]

    @_dec()
    async def create_fail() -> None:
        s = current_session()
        s.execute("INSERT INTO t (id, name) VALUES (2, 'b')")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await create_fail()
    rows = fac.create_session().query_all("SELECT name FROM t")
    assert rows == [{"name": "a"}]  # 第二条因异常回滚未落库


@pytest.mark.asyncio
async def test_transactional_bare_decorator_commits() -> None:
    """裸用 @transactional（不带括号）应默认 REQUIRED 并正常 commit。

    覆盖"可参数化装饰器"模式：`@transactional`（直接装饰函数）与 `@transactional(...)` 均可用，
    裸写默认 `Propagation.REQUIRED`。要求 commit 发生、rollback 未发生。
    """
    fac = _FakeFac()
    bind_components({"db": _FakeDb(fac)})

    @_dec  # 裸用（不带括号）：默认 REQUIRED
    async def create_order() -> str:
        s = current_session()
        await s.execute("INSERT INTO t_order ...")
        return "ok"

    result = await create_order()
    assert result == "ok"
    assert "commit" in fac.events
    assert "rollback" not in fac.events
