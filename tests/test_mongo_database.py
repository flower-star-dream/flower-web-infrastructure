"""
MongoDB SPI 测试（注册表 + 会话契约 + 默认实现 + create_app 装配）

@Author: 花海
@Date: 2026/08/18 10:30
@Description: 验证 MongoDB SPI 体系：
              1) MongoDatabaseRegistry 基础语义：内置 beanie 条目、注册/查询/实例化/注销/同名覆盖；
              2) BeanieMongoSession（默认实现）：集合级 CRUD 参数透传与返回值归一化
                 （AsyncMock 模拟集合，不触网）；
              3) MongoDatabase（默认工厂）：create_session / session 上下文 / register_document_models /
                 transaction / close / health_check（FakeConfig 替身，不触网）；
              4) create_app 装配：app.mongo.enabled=true 按 app.mongo.type 经注册表装配
                 （内置 beanie / 自定义 / 未注册快速失败）。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest

from web_infra.application import create_app
from web_infra.config import ConfigError
from web_infra.db import (
    MongoDatabaseFactoryInterface,
    MongoDatabaseRegistry,
    MongoSessionInterface,
)
from web_infra.db.beanie_mongo_session import BeanieMongoSession
from web_infra.db.mongo_database import MongoDatabase


@pytest.fixture
def clean_registry():
    """测试后清理全局 MongoDB 注册表（保留内置条目）"""
    before = dict(MongoDatabaseRegistry._factories)
    yield
    MongoDatabaseRegistry._factories.clear()
    MongoDatabaseRegistry._factories.update(before)


class _FakeMongoDatabase:
    """自定义 MongoDB 实现（仅验证注册表装配链路，无实际连接）"""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = params or {}

    async def create_session(self) -> Any:
        return None

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[Any, None]:
        yield None

    async def close(self) -> None:
        return None

    async def health_check(self) -> bool:
        return True


class _FakeConfig:
    """MongoDBConfig 替身（记录 connect/close 调用，不触网）"""

    def __init__(self) -> None:
        self.client: Any = None
        self.connect_calls: list[Any] = []
        self.closed = False
        self.metrics_refreshed = False
        self._database: dict[str, Any] = {}

    async def connect(self, document_models: Any = None) -> None:
        """记录连接调用（传 document_models 参数全量）"""
        self.client = object()
        self.connect_calls.append(document_models)

    async def close(self) -> None:
        self.closed = True
        self.client = None

    async def health_check(self) -> bool:
        return self.client is not None

    def get_database(self) -> Any:
        if self.client is None:
            raise RuntimeError("MongoDB 未连接")
        return self._database

    def update_pool_metrics(self) -> None:
        self.metrics_refreshed = True


def _make_session(coll: Any) -> BeanieMongoSession:
    """构造绑定假集合的会话（config.get_database() 返回 dict 容器）"""
    config = SimpleNamespace(get_database=lambda: {"t": coll})
    return BeanieMongoSession(config)


# ------------------------------------------------------------------
# 注册表基础语义
# ------------------------------------------------------------------


def test_builtin_beanie_registered(clean_registry):
    """内置 beanie 条目导入即注册"""
    assert "beanie" in MongoDatabaseRegistry.registered_names()


def test_register_overwrite_and_unregister(clean_registry):
    """同名覆盖 + 注销（不存在时静默），未注册 get 抛 KeyError"""
    MongoDatabaseRegistry.register("fake", lambda p: _FakeMongoDatabase({"v": 1}))
    MongoDatabaseRegistry.register("fake", lambda p: _FakeMongoDatabase({"v": 2}))
    assert MongoDatabaseRegistry.create("fake", {}).params["v"] == 2

    MongoDatabaseRegistry.unregister("fake")
    MongoDatabaseRegistry.unregister("fake")  # 重复注销静默
    with pytest.raises(KeyError):
        MongoDatabaseRegistry.get("fake")


def test_beanie_factory_builds_mongo_database():
    """内置 beanie 工厂实例化为 MongoDatabase（连接惰性，不触网）"""
    db = MongoDatabaseRegistry.create("beanie", {"url": "mongodb://localhost:27017", "database": "app"})
    assert isinstance(db, MongoDatabase)


# ------------------------------------------------------------------
# BeanieMongoSession（默认实现）CRUD
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_one_returns_id_str():
    """插入单条：返回 _id 字符串形式，参数透传"""
    coll = AsyncMock()
    coll.insert_one.return_value = SimpleNamespace(inserted_id="507f1f77bcf86cd799439011")
    session = _make_session(coll)
    result = await session.insert_one("t", {"name": "a"})
    assert result == "507f1f77bcf86cd799439011"
    coll.insert_one.assert_awaited_once_with({"name": "a"}, session=None)


@pytest.mark.asyncio
async def test_insert_many_returns_id_list():
    """批量插入：返回 _id 字符串列表"""
    coll = AsyncMock()
    coll.insert_many.return_value = SimpleNamespace(inserted_ids=["a", "b"])
    session = _make_session(coll)
    result = await session.insert_many("t", [{"n": 1}, {"n": 2}])
    assert result == ["a", "b"]
    coll.insert_many.assert_awaited_once_with([{"n": 1}, {"n": 2}], session=None)


@pytest.mark.asyncio
async def test_find_one_returns_dict_or_none():
    """查询单条：命中返回 dict，未命中返回 None"""
    coll = AsyncMock()
    coll.find_one.return_value = {"_id": "1", "name": "a"}
    session = _make_session(coll)
    result = await session.find_one("t", {"name": "a"}, sort=[("_id", 1)])
    assert result == {"_id": "1", "name": "a"}
    coll.find_one.assert_awaited_once_with({"name": "a"}, None, sort=[("_id", 1)], session=None)

    coll.find_one.return_value = None
    assert await session.find_one("t", {"name": "x"}) is None


@pytest.mark.asyncio
async def test_find_many_returns_list():
    """查询多条：游标 to_list 转 dict 列表，skip/limit 透传"""
    coll = AsyncMock()
    cursor = AsyncMock()
    cursor.to_list.return_value = [{"_id": "1"}, {"_id": "2"}]
    coll.find = MagicMock(return_value=cursor)  # find 为同步方法，返回游标
    session = _make_session(coll)
    result = await session.find_many("t", {"x": 1}, skip=1, limit=10)
    assert result == [{"_id": "1"}, {"_id": "2"}]
    coll.find.assert_called_once_with({"x": 1}, None, sort=None, skip=1, limit=10, session=None)
    cursor.to_list.assert_awaited_once_with(length=None)


@pytest.mark.asyncio
async def test_update_returns_modified_count():
    """更新单条/多条/替换：返回实际修改条数"""
    coll = AsyncMock()
    coll.update_one.return_value = SimpleNamespace(modified_count=1)
    coll.update_many.return_value = SimpleNamespace(modified_count=2)
    coll.replace_one.return_value = SimpleNamespace(modified_count=1)
    session = _make_session(coll)

    assert await session.update_one("t", {"_id": "1"}, {"$set": {"a": 2}}, upsert=True) == 1
    coll.update_one.assert_awaited_once_with(
        {"_id": "1"}, {"$set": {"a": 2}}, upsert=True, array_filters=None, session=None
    )

    assert await session.update_many("t", {"x": 1}, {"$set": {"a": 2}}) == 2
    coll.update_many.assert_awaited_once_with(
        {"x": 1}, {"$set": {"a": 2}}, upsert=False, array_filters=None, session=None
    )

    assert await session.replace_one("t", {"_id": "1"}, {"name": "b"}) == 1
    coll.replace_one.assert_awaited_once_with({"_id": "1"}, {"name": "b"}, upsert=False, session=None)


@pytest.mark.asyncio
async def test_delete_returns_deleted_count():
    """删除单条/多条：返回删除条数"""
    coll = AsyncMock()
    coll.delete_one.return_value = SimpleNamespace(deleted_count=1)
    coll.delete_many.return_value = SimpleNamespace(deleted_count=3)
    session = _make_session(coll)

    assert await session.delete_one("t", {"_id": "1"}) == 1
    coll.delete_one.assert_awaited_once_with({"_id": "1"}, session=None)

    assert await session.delete_many("t", {"x": 1}) == 3
    coll.delete_many.assert_awaited_once_with({"x": 1}, session=None)


@pytest.mark.asyncio
async def test_count_aggregate_distinct():
    """统计/聚合/去重：返回条数、dict 列表、取值列表"""
    coll = AsyncMock()
    coll.count_documents.return_value = 5
    cursor = AsyncMock()
    cursor.to_list.return_value = [{"total": 5}]
    coll.aggregate = MagicMock(return_value=cursor)  # aggregate 为同步方法，返回游标
    coll.distinct.return_value = ["a", "b"]
    session = _make_session(coll)

    assert await session.count("t", {"x": 1}) == 5
    coll.count_documents.assert_awaited_once_with({"x": 1}, session=None)

    assert await session.aggregate("t", [{"$group": {"_id": None}}]) == [{"total": 5}]
    coll.aggregate.assert_called_once_with([{"$group": {"_id": None}}], session=None)
    cursor.to_list.assert_awaited_once_with(length=None)

    assert await session.distinct("t", "name", {"x": 1}) == ["a", "b"]
    coll.distinct.assert_awaited_once_with("name", {"x": 1}, session=None)


@pytest.mark.asyncio
async def test_create_index_returns_name():
    """创建索引：返回索引名"""
    coll = AsyncMock()
    coll.create_index.return_value = "idx_name"
    session = _make_session(coll)
    result = await session.create_index("t", [("name", 1)], name="idx_name", unique=True)
    assert result == "idx_name"
    coll.create_index.assert_awaited_once_with([("name", 1)], name="idx_name", unique=True, session=None)


@pytest.mark.asyncio
async def test_commit_rollback_noop_without_transaction():
    """非事务会话：commit/rollback/close 为空操作不抛错"""
    session = _make_session(AsyncMock())
    await session.commit()
    await session.rollback()
    await session.close()


@pytest.mark.asyncio
async def test_commit_rollback_delegates_to_transaction_session():
    """事务会话：commit/rollback 委托 ClientSession 事务管理，close 释放事务会话"""
    mongo_session = AsyncMock()
    session = BeanieMongoSession(SimpleNamespace(get_database=lambda: {}), mongo_session)
    await session.commit()
    mongo_session.commit_transaction.assert_awaited_once()
    await session.rollback()
    mongo_session.abort_transaction.assert_awaited_once()
    await session.close()
    assert session._session is None


# ------------------------------------------------------------------
# MongoDatabase（默认工厂）契约
# ------------------------------------------------------------------


def test_mongo_database_satisfies_factory_protocol():
    """默认工厂满足 MongoDatabaseFactoryInterface 契约"""
    assert isinstance(MongoDatabase(_FakeConfig()), MongoDatabaseFactoryInterface)


def test_beanie_session_satisfies_session_protocol():
    """默认会话满足 MongoSessionInterface 契约"""
    session = _make_session(AsyncMock())
    assert isinstance(session, MongoSessionInterface)


@pytest.mark.asyncio
async def test_create_session_connects_lazily():
    """create_session：惰性建连（无模型时不初始化 ODM）并返回 BeanieMongoSession"""
    config = _FakeConfig()
    db = MongoDatabase(config)
    session = await db.create_session()
    assert config.client is not None
    assert isinstance(session, BeanieMongoSession)
    assert config.connect_calls == [None]


@pytest.mark.asyncio
async def test_session_context_commit_and_close(monkeypatch):
    """session() 上下文：退出自动提交并关闭（异常路径自动回滚）"""
    config = _FakeConfig()
    db = MongoDatabase(config)
    commit = AsyncMock()
    rollback = AsyncMock()
    close = AsyncMock()
    # 每次 create_session 生成新实例，故 patch 类方法统一断言
    monkeypatch.setattr(BeanieMongoSession, "commit", commit)
    monkeypatch.setattr(BeanieMongoSession, "rollback", rollback)
    monkeypatch.setattr(BeanieMongoSession, "close", close)

    async with db.session():
        pass
    commit.assert_awaited_once()
    rollback.assert_not_awaited()
    close.assert_awaited_once()

    commit.reset_mock()
    rollback.reset_mock()
    close.reset_mock()
    with pytest.raises(RuntimeError, match="boom"):
        async with db.session():
            raise RuntimeError("boom")
    commit.assert_not_awaited()
    rollback.assert_awaited_once()
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_register_document_models_registers_odm():
    """register_document_models：首次建连带模型初始化 ODM，已连接追加时全量重新 init_beanie"""
    config = _FakeConfig()
    db = MongoDatabase(config)

    class Dummy1:  # noqa: D106
        pass

    await db.register_document_models([Dummy1])
    assert config.client is not None
    assert config.connect_calls == [[Dummy1]]

    class Dummy2:  # noqa: D106
        pass

    await db.register_document_models([Dummy2])
    assert set(config.connect_calls[-1]) == {Dummy1, Dummy2}


@pytest.mark.asyncio
async def test_transaction_yields_bound_session():
    """transaction()：事务上下文 yield 绑定事务 session 的会话"""
    config = _FakeConfig()
    db = MongoDatabase(config)
    client = MagicMock()
    started = AsyncMock()
    mongo_session = MagicMock()
    mongo_session.start_transaction.return_value = AsyncMock()
    started.__aenter__.return_value = mongo_session
    client.start_session = AsyncMock(return_value=started)  # 异步方法，await 后返回会话上下文管理器
    config.client = client

    async with db.transaction() as session:
        assert isinstance(session, BeanieMongoSession)
        assert session._session is mongo_session


@pytest.mark.asyncio
async def test_close_and_health_check_delegate():
    """close / health_check / update_pool_metrics / get_database 委托给配置"""
    config = _FakeConfig()
    db = MongoDatabase(config)

    assert await db.health_check() is False  # 未连接
    await db.create_session()
    assert await db.health_check() is True

    db.update_pool_metrics()
    assert config.metrics_refreshed is True

    await db.close()
    assert config.closed is True

    with pytest.raises(RuntimeError):
        db.get_database()


# ------------------------------------------------------------------
# create_app 装配
# ------------------------------------------------------------------


def test_mongo_enabled_assembles_beanie(clean_registry):
    """app.mongo.enabled=true：默认 type=beanie 装配 MongoDatabase（连接惰性，不触网）"""
    app = create_app({"app": {"mongo": {"enabled": True}}})
    assert isinstance(app.state.mongo, MongoDatabase)


def test_mongo_custom_type_assembles(clean_registry):
    """自定义 MongoDB 实现经注册表注册后按 app.mongo.type 装配，连接参数透传"""
    MongoDatabaseRegistry.register("fake", lambda p: _FakeMongoDatabase(p))
    app = create_app({"app": {"mongo": {"enabled": True, "type": "fake", "database": "mydb"}}})
    mongo = app.state.mongo
    assert isinstance(mongo, _FakeMongoDatabase)
    assert mongo.params["database"] == "mydb"


def test_mongo_unknown_type_raises_config_error(clean_registry):
    """未注册的 mongo.type 启动期快速失败（ConfigError，避免拼写错误静默回落）"""
    with pytest.raises(ConfigError, match="not-exist"):
        create_app({"app": {"mongo": {"enabled": True, "type": "not-exist"}}})


def test_mongo_disabled_not_assembled():
    """默认 app.mongo.enabled=false：不装配 mongo 组件"""
    app = create_app({"app.name": "mongo-off"})
    assert "mongo" not in app.state.components
