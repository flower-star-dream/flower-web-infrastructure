"""
数据库 SPI 注册表测试（单源替换 + 混合多数据源）

@Author: 花海
@Date: 2026/08/17 18:30
@Description: 验证 DatabaseRegistry：
              1) 类级注册表基础语义：内置 mysql/sqlite、注册/查询/实例化/注销/同名覆盖；
              2) create_app 单源装配：app.db.type 命中注册表按名装配（默认 mysql / sqlite / 自定义 pg）；
              3) 混合多数据源（app.db.instances，每实例 type 可不同）：装配为 DatabaseManager
                 按名获取，MySQL 与 PostgreSQL 等不同数据库并存；
              4) 兼容旧格式（app.db.mysql.instances 多租户独立库，无 type 字段缺省 mysql）；
              5) 未注册的 type（单源/多源实例）启动期快速失败（ConfigError）。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import pytest

from web_infra.application import create_app
from web_infra.config import ConfigError
from web_infra.db import DatabaseFactoryInterface, DatabaseRegistry, SqliteSessionFactory
from web_infra.db.database_manager import DatabaseManager
from web_infra.db.mysql_database import MySQLDatabase


class _FakePgDatabase:
    """自定义 PostgreSQL 实现（仅验证注册表装配链路，无实际连接）"""

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


@pytest.fixture
def clean_registry():
    """测试后清理全局数据库注册表（保留内置条目）"""
    before = dict(DatabaseRegistry._factories)
    yield
    DatabaseRegistry._factories.clear()
    DatabaseRegistry._factories.update(before)


# ------------------------------------------------------------------
# 注册表基础语义
# ------------------------------------------------------------------


def test_builtin_entries_registered(clean_registry):
    """内置 mysql/sqlite 条目导入即注册"""
    assert set(DatabaseRegistry.registered_names()) == {"mysql", "sqlite"}


def test_register_overwrite_and_unregister(clean_registry):
    """同名覆盖 + 注销（不存在时静默），未注册 get 抛 KeyError"""
    DatabaseRegistry.register("pg", lambda p: _FakePgDatabase({"v": 1}))
    DatabaseRegistry.register("pg", lambda p: _FakePgDatabase({"v": 2}))
    assert DatabaseRegistry.create("pg", {}).params["v"] == 2

    DatabaseRegistry.unregister("pg")
    DatabaseRegistry.unregister("pg")  # 重复注销静默
    with pytest.raises(KeyError):
        DatabaseRegistry.get("pg")


# ------------------------------------------------------------------
# create_app 单源装配
# ------------------------------------------------------------------


def test_default_mysql_assembled(clean_registry):
    """默认 app.db.type=mysql：装配 MySQLDatabase"""
    app = create_app({"app.name": "default-db"})
    assert isinstance(app.state.db, MySQLDatabase)


def test_sqlite_assembled(clean_registry):
    """app.db.type=sqlite：装配 SqliteSessionFactory"""
    app = create_app({"app.db.type": "sqlite", "app.db.sqlite.path": ":memory:"})
    assert isinstance(app.state.db, SqliteSessionFactory)


def test_custom_db_type_assembles(clean_registry):
    """自定义数据库（如 PostgreSQL）经注册表注册后按 app.db.type 装配"""
    DatabaseRegistry.register("pg", lambda p: _FakePgDatabase(p))
    app = create_app({"app.db.type": "pg", "app.db.pg": {"host": "pg-host"}})
    db = app.state.db
    assert isinstance(db, _FakePgDatabase)
    assert db.params["host"] == "pg-host"  # 实例连接参数透传


def test_unknown_db_type_raises_config_error(clean_registry):
    """未注册的 db.type 启动期快速失败（ConfigError，避免静默回落 sqlite）"""
    with pytest.raises(ConfigError, match="not-exist"):
        create_app({"app.db.type": "not-exist"})


# ------------------------------------------------------------------
# 混合多数据源（app.db.instances）
# ------------------------------------------------------------------


def test_mixed_instances_assembles(clean_registry):
    """app.db.instances 混合多源：MySQL 与 PostgreSQL 并存，按名获取对应数据库"""
    DatabaseRegistry.register("pg", lambda p: _FakePgDatabase(p))
    app = create_app(
        {
            "app.db.instances": {
                "order": {"type": "mysql", "host": "mysql-host"},
                "audit": {"type": "pg", "host": "pg-host"},
            }
        }
    )
    db = app.state.db
    assert isinstance(db, DatabaseManager)
    assert isinstance(db.get("order"), MySQLDatabase)
    assert isinstance(db.get("audit"), _FakePgDatabase)
    assert db.get("audit").params["host"] == "pg-host"


def test_mixed_instances_default_type_mysql(clean_registry):
    """app.db.instances 实例未带 type 字段时缺省回落 mysql"""
    app = create_app({"app.db.instances": {"order": {"host": "mysql-host"}}})
    db = app.state.db
    assert isinstance(db, DatabaseManager)
    assert isinstance(db.get("order"), MySQLDatabase)


def test_same_type_instances_assembles(clean_registry):
    """同类型多库（app.db.instances 全部显式 type=mysql）：同样按 DatabaseManager 装配，按名获取"""
    app = create_app(
        {
            "app.db.instances": {
                "order": {"type": "mysql", "host": "mysql-1", "database": "order_db"},
                "inventory": {"type": "mysql", "host": "mysql-2", "database": "inventory_db"},
            }
        }
    )
    db = app.state.db
    assert isinstance(db, DatabaseManager)
    assert isinstance(db.get("order"), MySQLDatabase)
    assert isinstance(db.get("inventory"), MySQLDatabase)


def test_mixed_instances_unknown_type_raises(clean_registry):
    """多源实例 type 未注册：启动期快速失败（ConfigError）"""
    with pytest.raises(ConfigError, match="app.db.instances"):
        create_app({"app.db.instances": {"x": {"type": "not-exist"}}})


def test_legacy_mysql_instances_assembles(clean_registry):
    """兼容旧格式 app.db.mysql.instances（多租户独立库，全 MySQL）：装配 DatabaseManager"""
    app = create_app(
        {
            "app.db.mysql.instances": {
                "t1": {"host": "mysql-1"},
                "t2": {"host": "mysql-2"},
            }
        }
    )
    db = app.state.db
    assert isinstance(db, DatabaseManager)
    assert isinstance(db.get("t1"), MySQLDatabase)
    assert isinstance(db.get("t2"), MySQLDatabase)
