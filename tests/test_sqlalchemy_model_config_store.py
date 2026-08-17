"""
SQLAlchemy 模型配置来源测试

@Author: 花海
@Date: 2026/08/17 15:30
@Description: 验证（AI 规范 §3.2/§17.4）：
              1) SqlAlchemyModelConfigStore 数据库 CRUD 语义（sqlite+aiosqlite 内存库验证 SQL）；
              2) api_key 存 env:VAR 引用，resolved_api_key 运行时从环境变量解析（禁止明文落盘）；
              3) application 装配：store.type=db 时数据源跟随用户配置的数据库组件（mysql/sqlite），
                 拿不到异步会话工厂时快速失败；
              4) 启动生命周期：数据库模型配置来源自动同步 SPI 注册表。
"""
import os
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from web_infra.ai import (
    DictModelConfigStore,
    ModelConfig,
    ModelProviderFactory,
    ModelProviderRegistry,
    OpenAICompatibleProvider,
)
from web_infra.ai.sqlalchemy_model_config_store import SqlAlchemyModelConfigStore
from web_infra.application import Application, create_app
from web_infra.config import ConfigError

API_BASE = "http://mock.test/v1"

_CREATE_TABLE_SQL = """
CREATE TABLE ai_model_config (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    model_code          VARCHAR(128) NOT NULL UNIQUE,
    model_name          VARCHAR(255) NOT NULL,
    provider            VARCHAR(64)  NOT NULL DEFAULT 'openai_compatible',
    api_base            VARCHAR(512) NOT NULL,
    api_key             VARCHAR(512) NOT NULL,
    model_id            VARCHAR(255),
    max_tokens          INT NOT NULL DEFAULT 4096,
    temperature         NUMERIC NOT NULL DEFAULT 0,
    top_p               NUMERIC NOT NULL DEFAULT 0,
    timeout             INT NOT NULL DEFAULT 120,
    is_deterministic    TINYINT NOT NULL DEFAULT 0,
    stop                VARCHAR(1024),
    input_price_per_1k  NUMERIC NOT NULL DEFAULT 0,
    output_price_per_1k NUMERIC NOT NULL DEFAULT 0,
    created_at          DATETIME NOT NULL,
    updated_at          DATETIME
)
"""


def _config(**overrides: Any) -> ModelConfig:
    """构造最小模型配置（model_id 缺省回落 model_code）"""
    base: dict[str, Any] = dict(
        id=1,
        model_name="Mock Chat",
        model_code="mock-chat",
        provider="openai_compatible",
        api_base=API_BASE,
        api_key="env:LLM_API_KEY",
    )
    base.update(overrides)
    return ModelConfig(**base)


@pytest_asyncio.fixture
async def db_store():
    """sqlite+aiosqlite 内存库构造 SqlAlchemyModelConfigStore（验证 SQL 语义）"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text(_CREATE_TABLE_SQL))
        await session.commit()
    store = SqlAlchemyModelConfigStore(factory)
    yield store
    await engine.dispose()


@pytest.fixture
def clean_registry():
    """测试后清理全局供应商注册表，避免污染其他用例"""
    before = dict(ModelProviderRegistry._providers)
    yield
    ModelProviderRegistry._providers.clear()
    ModelProviderRegistry._providers.update(before)


@pytest.fixture
def clean_factory():
    """测试后清理供应商工厂注册表"""
    before = dict(ModelProviderFactory._factories)
    yield
    ModelProviderFactory._factories.clear()
    ModelProviderFactory._factories.update(before)


# ------------------------------------------------------------------
# Store CRUD 语义（sqlite 内存库）
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_missing_returns_none(db_store):
    """未配置的模型逻辑名返回 None（区别于缺失配置的 E4-AI-001）；空库默认模型同样返回 None"""
    assert await db_store.load("not-exist") is None
    assert await db_store.load(None) is None


@pytest.mark.asyncio
async def test_load_none_returns_first_as_default(db_store):
    """未传 model_code（默认模型场景）返回按 id 升序首条，与 DictModelConfigStore 默认语义对齐"""
    await db_store.upsert(_config(id=0, model_code="mock-embed", model_name="Mock Embed"))
    await db_store.upsert(_config(id=0))
    loaded = await db_store.load(None)
    assert loaded is not None
    assert loaded.model_code == "mock-embed"


@pytest.mark.asyncio
async def test_upsert_insert_then_load(db_store):
    """upsert 插入 -> load 按 model_code 返回，插入场景回填数据库自增 id"""
    saved = await db_store.upsert(_config(id=0))
    assert saved.id > 0  # 数据库自增 id 回填

    loaded = await db_store.load("mock-chat")
    assert loaded is not None
    assert loaded.id == saved.id
    assert loaded.model_name == "Mock Chat"
    assert loaded.model_code == "mock-chat"
    assert loaded.provider == "openai_compatible"
    assert loaded.api_base == API_BASE
    assert loaded.api_key == "env:LLM_API_KEY"  # 数据库存的是引用而非明文


@pytest.mark.asyncio
async def test_upsert_update_existing(db_store):
    """upsert 已存在 model_code 时更新而非重复插入（幂等语义，§17.4）"""
    await db_store.upsert(_config())
    updated = await db_store.upsert(_config(model_name="Mock Chat v2", max_tokens=8192, temperature=0.7))
    assert updated.id == 1  # 同一行更新，id 不变

    loaded = await db_store.load("mock-chat")
    assert loaded.model_name == "Mock Chat v2"
    assert loaded.max_tokens == 8192
    assert loaded.temperature == 0.7
    assert len(await db_store.load_all()) == 1


@pytest.mark.asyncio
async def test_load_all_orders_by_id(db_store):
    """load_all 返回全部模型配置（按 id 升序，页面化配置自动注册依据）"""
    await db_store.upsert(_config())
    await db_store.upsert(_config(id=0, model_code="mock-embed", model_name="Mock Embed", model_id="embed-1"))
    configs = await db_store.load_all()
    assert [c.model_code for c in configs] == ["mock-chat", "mock-embed"]
    assert configs[1].model_id == "embed-1"


@pytest.mark.asyncio
async def test_stop_list_json_roundtrip(db_store):
    """stop 列表字段 JSON 序列化往返无损（单字符串保持原样）"""
    await db_store.upsert(_config(stop=["<|end|>", "stop1"]))
    assert (await db_store.load("mock-chat")).stop == ["<|end|>", "stop1"]

    await db_store.upsert(_config(stop="单字符串停止词"))
    assert (await db_store.load("mock-chat")).stop == "单字符串停止词"


@pytest.mark.asyncio
async def test_numeric_and_bool_fields_roundtrip(db_store):
    """数值/布尔字段往返无损（Decimal/字符串数值归一为 float，SQLite TINYINT -> bool）"""
    await db_store.upsert(
        _config(
            is_deterministic=True,
            timeout=30,
            input_price_per_1k=0.001234,
            output_price_per_1k=0.002345,
            top_p=0.9,
        )
    )
    loaded = await db_store.load("mock-chat")
    assert loaded.is_deterministic is True
    assert loaded.timeout == 30
    assert loaded.input_price_per_1k == 0.001234
    assert loaded.output_price_per_1k == 0.002345
    assert loaded.top_p == 0.9


@pytest.mark.asyncio
async def test_env_ref_resolved_from_environment(db_store, monkeypatch):
    """api_key 存 env: 引用：load 后 resolved_api_key 从环境变量解析（禁止明文落盘，AI 规范 §3.1/AI-7）"""
    await db_store.upsert(_config())
    monkeypatch.setenv("LLM_API_KEY", "sk-secret-from-env")
    loaded = await db_store.load("mock-chat")
    assert loaded.resolved_api_key == "sk-secret-from-env"
    # 环境变量缺失时原样返回引用（便于排查配置错误，与 ModelConfig 既有语义一致）
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert (await db_store.load("mock-chat")).resolved_api_key == "env:LLM_API_KEY"


@pytest.mark.asyncio
async def test_store_feeds_auto_registrar(db_store, clean_registry, monkeypatch):
    """数据库 Store 接入 ModelAutoRegistrar：register_from_store 全量注册供应商进 SPI 注册表"""
    await db_store.upsert(_config())
    monkeypatch.setenv("LLM_API_KEY", "sk-secret-from-env")
    from web_infra.ai import ModelAutoRegistrar

    registered = await ModelAutoRegistrar().register_from_store(db_store)
    assert registered == ["mock-chat"]
    assert ModelProviderRegistry.contains("mock-chat")
    provider = ModelProviderRegistry.get("mock-chat")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._config.resolved_api_key == "sk-secret-from-env"  # 注册时即携带解析后的密钥引用


# ------------------------------------------------------------------
# application 装配（store.type=db）
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_application_db_store_sqlite_assembles(clean_registry):
    """app.ai.store.type=db 且数据库组件为 sqlite（app.db.type=sqlite）时正常装配（数据源跟随用户配置，不锁死 MySQL）"""
    settings = {
        "app": {
            "ai": {"enabled": True, "store": {"type": "db"}, "models": [], "model_gateway": {}},
            "db": {"type": "sqlite", "sqlite": {"path": ":memory:"}},
        }
    }
    app = create_app(settings)
    store = app.state.ai_model_config_store
    assert isinstance(store, SqlAlchemyModelConfigStore)
    assert store._engine is not None  # sqlite 场景自建独立 aiosqlite 引擎
    await store.close()  # close 释放自建引擎


def test_application_db_store_missing_session_factory_raises(clean_registry):
    """db 组件拿不到 SQLAlchemy 异步会话工厂时快速失败（ConfigError，明确错误提示）"""
    class _NoSessionFactory:
        pass

    settings = {
        "app": {
            "ai": {"enabled": True, "store": {"type": "db"}, "models": [], "model_gateway": {}},
            "db": {"type": "sqlite", "sqlite": {"path": ":memory:"}},
        }
    }
    app = Application(settings)
    app._components["db"] = _NoSessionFactory()
    with pytest.raises(ConfigError):
        app._build_ai_model_store()


@pytest.mark.asyncio
async def test_application_db_store_registers_on_lifespan(clean_registry, monkeypatch):
    """store.type=db：启动生命周期自动同步 SPI 注册表（页面化配置自动注册，AI 规范 §17.4）"""
    store = DictModelConfigStore({"m1": _config(model_code="m1", api_key="env:LLM_API_KEY")})
    monkeypatch.setattr(Application, "_build_ai_model_store", lambda self: store)
    monkeypatch.setenv("LLM_API_KEY", "sk-secret-from-env")

    settings = {
        "app": {
            "ai": {
                "enabled": True,
                "store": {"type": "db"},
                "models": [],
                "model_gateway": {"default_scene": "chat", "routes": {"chat": {"primary": "m1", "backups": []}}},
            }
        }
    }
    app = create_app(settings)
    assert app.state.ai_model_config_store is store
    async with app.router.lifespan_context(app):  # 触发启动段（register_from_store）
        assert ModelProviderRegistry.contains("m1")
