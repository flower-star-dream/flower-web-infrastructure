"""
数据库命名数据源（datasources）装配测试

@Author: 花海
@Date: 2026/08/22 11:00
@Description: 验证 app.db.datasources 命名池装配（default 指向默认数据源、按名路由）、
              与旧 app.db.type+app.db.mysql 单源形态的向后兼容（二选一，datasources 优先）。
              使用 sqlite 最小实现，不触网。
"""
import pytest

from web_infra import create_app
from web_infra.capabilities.db import DatabaseManager, SqliteSessionFactory


@pytest.mark.asyncio
async def test_datasources_pool_assembly_and_default():
    """datasources 命名池：default 指向默认数据源，按名取各自会话工厂"""
    app = create_app(
        settings={
            "app.db.default": "primary",
            "app.db.datasources": {
                "primary": {"type": "sqlite", "path": ":memory:"},
                "audit": {"type": "sqlite", "path": ":memory:"},
            },
        }
    )
    db = app.state.db
    assert isinstance(db, DatabaseManager)
    assert "primary" in db.names
    assert "audit" in db.names
    # default 指向 primary
    assert db._default_name == "primary"


@pytest.mark.asyncio
async def test_datasources_override_legacy_single_source():
    """datasources 段非空时优先；旧 app.db.type 单源形态仍可用（向后兼容）"""
    app = create_app(
        settings={
            "app.db.type": "sqlite",
            "app.db.sqlite": {"path": ":memory:"},
            "app.db.datasources": {
                "primary": {"type": "sqlite", "path": ":memory:"},
            },
        }
    )
    db = app.state.db
    assert isinstance(db, DatabaseManager)
    assert "primary" in db.names


@pytest.mark.asyncio
async def test_legacy_single_source_still_works():
    """向后兼容：未配置 datasources 时走旧 app.db.type 单源形态"""
    app = create_app(settings={"app.db.type": "sqlite", "app.db.sqlite": {"path": ":memory:"}})
    db = app.state.db
    assert not isinstance(db, DatabaseManager)
    assert isinstance(db, SqliteSessionFactory)
