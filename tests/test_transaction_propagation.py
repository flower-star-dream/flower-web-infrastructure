"""
事务传播模块单元测试

@Author: 花海
@Date: 2026/08/22 10:00
@Description: 验证事务栈（ContextVar）push/pop/current、rollback-only 标记与枚举常量。
"""
import pytest

from web_infra.capabilities.db.transaction_propagation import (
    IsolationLevel,
    Propagation,
    TransactionFrame,
    current_session,
    current_transaction,
    mark_rollback_only,
    pop_transaction,
    push_transaction,
)


@pytest.fixture(autouse=True)
def _clean_stack():
    """每个用例后清空事务栈，防止脏栈污染后续用例"""
    yield
    from web_infra.capabilities.db import transaction_propagation as tp

    tp._TX_STACK.set(())


def test_propagation_enum_values():
    """传播枚举值对齐 Spring 语义"""
    assert Propagation.REQUIRED.value == "REQUIRED"
    assert Propagation.REQUIRES_NEW.value == "REQUIRES_NEW"
    assert Propagation.NESTED.value == "NESTED"


def test_isolation_level_constants():
    """隔离级别常量（SQLAlchemy 兼容字符串；DEFAULT=None 让数据库用默认）"""
    assert IsolationLevel.DEFAULT is None
    assert IsolationLevel.READ_COMMITTED == "READ COMMITTED"
    assert IsolationLevel.REPEATABLE_READ == "REPEATABLE READ"
    assert IsolationLevel.SERIALIZABLE == "SERIALIZABLE"


def test_push_pop_current_transaction():
    """push/pop/current：栈顶即最近压入；pop 后恢复外层"""
    assert current_transaction() is None
    frame1 = push_transaction("s1", owner=True)
    frame2 = push_transaction("s2", owner=False)
    assert current_transaction() is frame2
    assert current_session() == "s2"
    assert pop_transaction() is frame2
    assert current_transaction() is frame1
    pop_transaction()
    assert current_transaction() is None


def test_pop_empty_returns_none():
    """空栈 pop 返回 None"""
    assert pop_transaction() is None


def test_mark_rollback_only_marks_outer_owner():
    """rollback-only 标记最近一个 owner 帧（内层异常时由最外层统一回滚）"""
    outer = push_transaction("outer", owner=True)
    inner = push_transaction("inner", owner=False)
    mark_rollback_only()
    assert inner.rollback_only is False
    assert outer.rollback_only is True
    pop_transaction()
    pop_transaction()


# ------------------------------------------------------------------
# Task 2: SessionScopeMixin 传播语义（Fake 会话，验证生命周期）
# ------------------------------------------------------------------
from web_infra.capabilities.db import SessionScopeMixin
from web_infra.capabilities.db.transaction_propagation import (
    TransactionPropagationError,
)


class _FakeFactory2:
    """模拟异步工厂：记录 commit/rollback/close 事件（验证传播生命周期）"""

    def __init__(self) -> None:
        self.events: list[str] = []

    async def create_session(self) -> "_FakeSession2":
        return _FakeSession2(self)

    async def close(self) -> None:
        pass

    async def health_check(self) -> bool:
        return True


class _FakeSession2:
    """模拟通用会话（DatabaseSessionInterface 语义）"""

    def __init__(self, factory: _FakeFactory2) -> None:
        self.factory = factory

    async def commit(self) -> None:
        self.factory.events.append("commit")

    async def rollback(self) -> None:
        self.factory.events.append("rollback")

    async def close(self) -> None:
        self.factory.events.append("close")


def _make_factory():
    class Factory(_FakeFactory2, SessionScopeMixin):
        pass

    return Factory()


@pytest.mark.asyncio
async def test_required_outer_commits_inner_reuses():
    """REQUIRED：内层复用外层会话，不 commit/close；外层统一提交"""
    factory = _make_factory()
    async with factory.session():  # 外层 owner
        async with factory.session():  # 内层 REQUIRED 复用
            pass
    assert factory.events == ["commit", "close"]


@pytest.mark.asyncio
async def test_required_inner_error_marks_outer_rollback_only():
    """REQUIRED：内层异常标记外层 rollback-only，外层提交被强制回滚并抛错"""
    factory = _make_factory()
    with pytest.raises(TransactionPropagationError):
        async with factory.session():
            try:
                async with factory.session():
                    raise ValueError("inner boom")
            except ValueError:
                pass  # 外层吞掉内层异常
    assert factory.events == ["rollback", "close"]


@pytest.mark.asyncio
async def test_requires_new_creates_independent_transaction():
    """REQUIRES_NEW：内层独立事务（自提交/自关闭），不影响外层"""
    from web_infra.capabilities.db.transaction_propagation import Propagation

    factory = _make_factory()
    async with factory.session():
        async with factory.session(propagation=Propagation.REQUIRES_NEW):
            pass
    # 外层 commit/close + 内层 commit/close
    assert factory.events == ["commit", "close", "commit", "close"]


@pytest.mark.asyncio
async def test_nested_without_outer_falls_back_to_required():
    """NESTED：无外层事务时退化为新建事务（对齐 Spring）"""
    from web_infra.capabilities.db.transaction_propagation import Propagation

    factory = _make_factory()
    async with factory.session(propagation=Propagation.NESTED):
        pass
    assert factory.events == ["commit", "close"]


# ------------------------------------------------------------------
# Task 3: MySQLDatabase 集成（sqlite+aiosqlite 文件库，传播语义）
# ------------------------------------------------------------------
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from web_infra.capabilities.db import MySQLDatabase, SqlAlchemyDatabaseSession
from web_infra.capabilities.db.transaction_propagation import Propagation


@pytest_asyncio.fixture
async def mysql_db(tmp_path):
    """绑定 sqlite+aiosqlite 文件库的 MySQLDatabase（传播语义与真实 MySQL 一致）"""
    url = f"sqlite+aiosqlite:///{tmp_path.as_posix()}/prop.db"
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class _FakeConfig:
        async def new_session(self):
            return factory()

    db = MySQLDatabase(_FakeConfig())  # type: ignore[arg-type]
    async with db.orm_session() as session:
        await session.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)"))
    yield db
    await engine.dispose()


@pytest.mark.asyncio
async def test_required_reuses_outer_transaction(mysql_db):
    """REQUIRED：内层与外层同一事务，外层提交内层数据可见"""
    async with mysql_db.orm_session() as outer:
        await outer.execute(text("INSERT INTO t (name) VALUES (:name)"), {"name": "outer"})
        async with mysql_db.orm_session() as inner:
            # 内层复用的是外层同一 AsyncSession（同一事务）
            await inner.execute(text("INSERT INTO t (name) VALUES (:name)"), {"name": "inner"})
    async with mysql_db.orm_session() as check:
        names = (await check.execute(text("SELECT name FROM t ORDER BY id"))).scalars().all()
    assert names == ["outer", "inner"]


@pytest.mark.asyncio
async def test_requires_new_commits_independently(mysql_db):
    """REQUIRES_NEW：内层独立提交，外层回滚不影响内层。

    注：sqlite 文件库单写连接限制，外层不持有未提交写锁（内层独立写并提交释放后外层才回滚），
    以验证"内层独立提交不被外层回滚影响"的语义（MySQL 行级锁多连接可写，无此限制）。
    """
    with pytest.raises(RuntimeError):
        async with mysql_db.orm_session() as outer:
            async with mysql_db.orm_session(propagation=Propagation.REQUIRES_NEW) as inner:
                await inner.execute(text("INSERT INTO t (name) VALUES (:name)"), {"name": "inner"})
            # 内层已独立提交并释放连接
            raise RuntimeError("outer boom")
    async with mysql_db.orm_session() as check:
        names = (await check.execute(text("SELECT name FROM t"))).scalars().all()
    assert names == ["inner"]


@pytest.mark.asyncio
async def test_nested_savepoint_rolls_back_inner_only(mysql_db):
    """NESTED：内层异常仅回滚到 SAVEPOINT，外层继续提交成功"""
    async with mysql_db.orm_session() as outer:
        await outer.execute(text("INSERT INTO t (name) VALUES (:name)"), {"name": "outer"})
        with pytest.raises(ValueError):
            async with mysql_db.orm_session(propagation=Propagation.NESTED) as inner:
                await inner.execute(text("INSERT INTO t (name) VALUES (:name)"), {"name": "nested"})
                raise ValueError("inner boom")
        await outer.execute(text("INSERT INTO t (name) VALUES (:name)"), {"name": "after"})
    async with mysql_db.orm_session() as check:
        names = (await check.execute(text("SELECT name FROM t ORDER BY id"))).scalars().all()
    assert names == ["outer", "after"]


@pytest.mark.asyncio
async def test_required_inner_error_forces_outer_rollback(mysql_db):
    """REQUIRED：内层异常 → rollback-only → 外层提交被强制回滚并抛错"""
    from web_infra.capabilities.db.transaction_propagation import TransactionPropagationError

    with pytest.raises(TransactionPropagationError):
        async with mysql_db.orm_session() as outer:
            await outer.execute(text("INSERT INTO t (name) VALUES (:name)"), {"name": "outer"})
            try:
                async with mysql_db.orm_session() as inner:
                    await inner.execute(text("INSERT INTO t (name) VALUES (:name)"), {"name": "inner"})
                    raise ValueError("inner boom")
            except ValueError:
                pass  # 外层吞掉内层异常
    async with mysql_db.orm_session() as check:
        names = (await check.execute(text("SELECT name FROM t"))).scalars().all()
    assert names == []  # 外层事务整体回滚


@pytest.mark.asyncio
async def test_generic_and_orm_session_mix_in_required(mysql_db):
    """REQUIRED：通用会话（文本 SQL）与 ORM 会话混用嵌套复用同一事务"""
    async with mysql_db.orm_session() as outer:
        async with mysql_db.session() as inner:  # 通用会话包装复用外层 AsyncSession
            await inner.execute(
                "INSERT INTO t (name) VALUES (:name)", {"name": "mixed"}
            )
    async with mysql_db.orm_session() as check:
        names = (await check.execute(text("SELECT name FROM t"))).scalars().all()
    assert names == ["mixed"]


# ------------------------------------------------------------------
# Task 4: MySQLConfig 引擎级隔离级别（含 DEFAULT 不注入）
# ------------------------------------------------------------------
from web_infra.capabilities.db import MySQLConfig


@pytest.mark.asyncio
async def test_mysql_config_engine_isolation_level(monkeypatch):
    """配置级隔离级别传入 create_async_engine（主库引擎级生效）"""
    from unittest.mock import AsyncMock, MagicMock

    captured: dict = {}
    fake_engine = MagicMock()
    # async with engine.connect() as conn：__aenter__ 异步返回 conn，conn.execute 为 AsyncMock（SELECT 1）
    fake_engine.connect.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    fake_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)
    fake_engine.dispose = AsyncMock()
    # 事件注册面向真实引擎，mock 引擎跳过（与隔离级别无关）
    monkeypatch.setattr("web_infra.capabilities.db.mysql_config.MySQLConfig._register_sql_timing_events", lambda self, e: None)
    monkeypatch.setattr("web_infra.capabilities.db.mysql_config.MySQLConfig._register_pool_leak_events", lambda self, e: None)

    def fake_create_async_engine(*args, **kwargs):
        captured.update(kwargs)
        return fake_engine

    monkeypatch.setattr("web_infra.capabilities.db.mysql_config.create_async_engine", fake_create_async_engine)
    config = MySQLConfig(url="mysql+aiomysql://u:p@h/db", isolation_level="READ COMMITTED")
    await config.connect()
    assert captured.get("isolation_level") == "READ COMMITTED"
    await config.close()


@pytest.mark.asyncio
async def test_mysql_config_engine_isolation_level_default_not_injected(monkeypatch):
    """DEFAULT/None：不注入 isolation_level，让数据库使用默认（MySQL InnoDB 为 REPEATABLE READ）"""
    from unittest.mock import AsyncMock, MagicMock

    captured: dict = {}
    fake_engine = MagicMock()
    fake_engine.connect.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    fake_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr("web_infra.capabilities.db.mysql_config.MySQLConfig._register_sql_timing_events", lambda self, e: None)
    monkeypatch.setattr("web_infra.capabilities.db.mysql_config.MySQLConfig._register_pool_leak_events", lambda self, e: None)

    def fake_create_async_engine(*args, **kwargs):
        captured.update(kwargs)
        return fake_engine

    monkeypatch.setattr("web_infra.capabilities.db.mysql_config.create_async_engine", fake_create_async_engine)
    config = MySQLConfig(url="mysql+aiomysql://u:p@h/db", isolation_level=IsolationLevel.DEFAULT)  # None：不注入
    await config.connect()
    assert "isolation_level" not in captured
    await config.close()


# ------------------------------------------------------------------
# Task 7: SqliteSessionFactory 同步支持三种传播（文件库）
# ------------------------------------------------------------------
import sqlite3

from web_infra.capabilities.db import SqliteSessionFactory


@pytest.fixture()
def sqlite_factory(tmp_path):
    """文件库 SqliteSessionFactory（REQUIRES_NEW 独立连接共享同一数据文件）"""
    factory = SqliteSessionFactory(db_path=str(tmp_path / "sync.db"))
    factory.create_session().execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    yield factory
    factory.close()


@pytest.mark.asyncio
async def test_sqlite_required_reuses_outer_connection(sqlite_factory):
    """SQLite REQUIRED：内层复用外层连接，外层提交数据可见"""
    async with sqlite_factory.session() as outer:
        outer.execute("INSERT INTO t (id, name) VALUES (1, 'a')")
        async with sqlite_factory.session() as inner:
            inner.execute("INSERT INTO t (id, name) VALUES (2, 'b')")
    rows = sqlite_factory.create_session().query_all("SELECT name FROM t ORDER BY id")
    assert rows == [{"name": "a"}, {"name": "b"}]


@pytest.mark.asyncio
async def test_sqlite_requires_new_independent_connection(sqlite_factory):
    """SQLite REQUIRES_NEW：独立连接独立提交，外层回滚不影响内层。

    注：sqlite 文件库单写连接限制，外层不持有未提交写锁（内层独立写并提交释放后外层才回滚）。
    """
    with pytest.raises(RuntimeError):
        async with sqlite_factory.session() as outer:
            async with sqlite_factory.session(propagation=Propagation.REQUIRES_NEW) as inner:
                inner.execute("INSERT INTO t (id, name) VALUES (2, 'b')")
            # 内层独立提交并释放连接
            raise RuntimeError("outer boom")
    rows = sqlite_factory.create_session().query_all("SELECT name FROM t ORDER BY id")
    assert rows == [{"name": "b"}]


@pytest.mark.asyncio
async def test_sqlite_nested_savepoint_rolls_back_inner_only(sqlite_factory):
    """SQLite NESTED：原生 SAVEPOINT，内层异常仅回滚保存点"""
    async with sqlite_factory.session() as outer:
        outer.execute("INSERT INTO t (id, name) VALUES (1, 'a')")
        with pytest.raises(ValueError):
            async with sqlite_factory.session(propagation=Propagation.NESTED) as inner:
                inner.execute("INSERT INTO t (id, name) VALUES (2, 'b')")
                raise ValueError("boom")
        outer.execute("INSERT INTO t (id, name) VALUES (3, 'c')")
    rows = sqlite_factory.create_session().query_all("SELECT name FROM t ORDER BY id")
    assert rows == [{"name": "a"}, {"name": "c"}]


@pytest.mark.asyncio
async def test_sqlite_required_inner_error_forces_outer_rollback(sqlite_factory):
    """SQLite REQUIRED：内层异常 → rollback-only → 外层提交被强制回滚"""
    from web_infra.capabilities.db.transaction_propagation import TransactionPropagationError

    with pytest.raises(TransactionPropagationError):
        async with sqlite_factory.session() as outer:
            outer.execute("INSERT INTO t (id, name) VALUES (1, 'a')")
            try:
                async with sqlite_factory.session() as inner:
                    inner.execute("INSERT INTO t (id, name) VALUES (2, 'b')")
                    raise ValueError("boom")
            except ValueError:
                pass
    rows = sqlite_factory.create_session().query_all("SELECT name FROM t")
    assert rows == []


# ------------------------------------------------------------------
# Task 9: db 模块导出传播符号（最小安装无第三方依赖可导入）
# ------------------------------------------------------------------
def test_db_module_exports_propagation_symbols():
    """db 模块导出传播相关符号（无第三方依赖，可安全导入）"""
    from web_infra.capabilities import db as db_module

    assert db_module.Propagation is Propagation
    assert db_module.IsolationLevel is IsolationLevel
    assert db_module.TransactionPropagationError is TransactionPropagationError


# ------------------------------------------------------------------
# Task 6: DatabaseManager.session/orm_session 透传传播与隔离级别
# ------------------------------------------------------------------
from unittest.mock import AsyncMock
from contextlib import asynccontextmanager

from web_infra.capabilities.db import DatabaseManager


@pytest.mark.asyncio
async def test_database_manager_passthrough_propagation_and_isolation():
    """DatabaseManager.session/orm_session 透传 propagation/isolation_level"""
    captured: dict = {}

    class _FakeDb:
        @asynccontextmanager
        async def session(self, **kwargs):
            captured["session_kwargs"] = kwargs
            yield "session"

        @asynccontextmanager
        async def orm_session(self, **kwargs):
            captured["orm_session_kwargs"] = kwargs
            yield "orm"

    manager = DatabaseManager({"default": _FakeDb()}, enforce_tenant_check=False)
    async with manager.session(propagation=Propagation.REQUIRES_NEW, isolation_level="SERIALIZABLE"):
        pass
    async with manager.orm_session(propagation=Propagation.NESTED, isolation_level="READ COMMITTED"):
        pass
    assert captured["session_kwargs"] == {
        "propagation": Propagation.REQUIRES_NEW,
        "isolation_level": "SERIALIZABLE",
    }
    assert captured["orm_session_kwargs"] == {
        "propagation": Propagation.NESTED,
        "isolation_level": "READ COMMITTED",
    }


# ------------------------------------------------------------------
# Task 5: 会话级隔离级别（mock 断言覆盖 + REQUIRED 复用忽略）
# ------------------------------------------------------------------
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_orm_session_applies_session_isolation_level():
    """会话级隔离级别：在事务创建点经 connection(execution_options=...) 覆盖"""
    fake_session = AsyncMock()
    fake_session.connection = AsyncMock(return_value=AsyncMock())
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    fake_session.close = AsyncMock()

    class _Config:
        async def new_session(self):
            return fake_session

    db = MySQLDatabase(_Config())  # type: ignore[arg-type]
    async with db.orm_session(isolation_level="SERIALIZABLE"):
        pass
    fake_session.connection.assert_awaited_once_with(
        execution_options={"isolation_level": "SERIALIZABLE"}
    )
    fake_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_required_reuse_ignores_isolation_level():
    """REQUIRED 复用外层时忽略隔离级别参数（避免污染外层连接）"""
    fake_outer = AsyncMock()
    fake_outer.connection = AsyncMock(return_value=AsyncMock())
    fake_outer.commit = AsyncMock()
    fake_outer.rollback = AsyncMock()
    fake_outer.close = AsyncMock()

    class _Config:
        async def new_session(self):
            return fake_outer

    db = MySQLDatabase(_Config())  # type: ignore[arg-type]
    async with db.orm_session() as outer:
        # 内层 REQUIRED + isolation_level：应复用外层，不触发 connection(execution_options=...)
        async with db.orm_session(isolation_level="READ COMMITTED") as inner:
            assert inner is outer
    # 外层仅创建时应用了隔离级别（connection 调用一次，由外层 new_session 触发）
    assert fake_outer.connection.await_count <= 1
