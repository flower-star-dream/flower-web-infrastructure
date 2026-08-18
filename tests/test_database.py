"""
通用数据库接口单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证通用数据库交互接口（DatabaseSessionInterface/DatabaseFactoryInterface SPI）与 SQLAlchemy 会话适配，
              及 orm_session() ORM 会话自动管理生命周期（提交/回滚/关闭，规范 §10.6）。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from web_infra.capabilities.db import (
    DatabaseFactoryInterface,
    MySQLConfig,
    MySQLConnectionSettings,
    MySQLDatabase,
    SqlAlchemyDatabaseSession,
)


def test_mysql_database_implements_database_factory():
    """MySQLDatabase 实现通用 DatabaseFactoryInterface SPI"""
    db = MySQLDatabase(MySQLConfig(settings=MySQLConnectionSettings(host="localhost")))
    assert isinstance(db, DatabaseFactoryInterface)


@pytest.mark.asyncio
async def test_sqlalchemy_database_session_crud(tmp_path):
    """通用 DatabaseSessionInterface 适配 SQLAlchemy AsyncSession 的 CRUD"""
    url = f"sqlite+aiosqlite:///{tmp_path.as_posix()}/test.db"
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    session = SqlAlchemyDatabaseSession(factory())
    await session.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    await session.execute("INSERT INTO t (name) VALUES (:name)", {"name": "a"})
    await session.commit()

    assert await session.query_all("SELECT * FROM t") == [{"id": 1, "name": "a"}]
    assert (await session.query_one("SELECT * FROM t WHERE id=:id", {"id": 1}))["name"] == "a"

    await session.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_mysql_database_orm_session_commit_and_rollback(tmp_path):
    """orm_session 上下文：退出自动提交、异常自动回滚、会话自动关闭（规范 §10.6）"""
    url = f"sqlite+aiosqlite:///{tmp_path.as_posix()}/orm.db"
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class _FakeConfig:
        """仅提供 new_session 的最小配置替身（复用 sqlite+aiosqlite 会话工厂）"""

        async def new_session(self):
            return factory()

    db = MySQLDatabase(_FakeConfig())  # type: ignore[arg-type]

    # 提交路径：退出上下文自动 commit
    async with db.orm_session() as session:
        await session.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)"))
        await session.execute(text("INSERT INTO t (name) VALUES (:name)"), {"name": "a"})
    # 退出后会话已自动关闭（自动释放连接，规范 §10.6）

    # 回滚路径：异常自动 rollback，不留脏数据
    with pytest.raises(RuntimeError):
        async with db.orm_session() as session:
            await session.execute(text("INSERT INTO t (name) VALUES (:name)"), {"name": "b"})
            raise RuntimeError("boom")

    # 提交的数据可见，回滚的数据不可见
    async with db.orm_session() as session:
        names = (await session.execute(text("SELECT name FROM t"))).scalars().all()
    assert names == ["a"]

    await engine.dispose()
