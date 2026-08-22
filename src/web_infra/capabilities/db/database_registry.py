"""
数据库注册表

@Author: 花海
@Date: 2026/08/17 18:00
@Description: 数据库 SPI 注册表：按 type 名注册/查询 DatabaseFactoryInterface 工厂，
              装配期（app.db.type 单源 / app.db.instances 混合多源）按名实例化；
              内置 mysql/sqlite 条目，用户自定义数据库（PostgreSQL 等）经 register 注册后
              即可接入 create_app（单库替换或与其他数据库并存），无需改动框架装配代码；
              未注册的 type 装配期快速失败（ConfigError）。
"""
from __future__ import annotations

from typing import Any, Callable

from web_infra.capabilities.db.database_factory_interface import DatabaseFactoryInterface
from web_infra.core.spi import SpiRegistry

#: 数据库工厂签名：入参实例连接参数（单源取 app.db.<type> 段，混合多源取 app.db.instances 实例项），
#: 返回数据库工厂实现（DatabaseFactoryInterface，可含 session_factory/orm_session 等扩展能力）
DatabaseFactory = Callable[[dict[str, Any]], DatabaseFactoryInterface]


class DatabaseRegistry(SpiRegistry):
    """数据库注册表（SpiRegistry 基类：命名空间隔离 + 内置默认保护；同名覆盖默认拒绝）"""

    @classmethod
    def create(cls, name: str, params: dict[str, Any]) -> DatabaseFactoryInterface:
        """按名实例化数据库；未注册抛 KeyError"""
        return cls.get(name)(params)


def _mysql_factory(params: dict[str, Any]) -> DatabaseFactoryInterface:
    """内置 mysql：MySQL 数据库工厂（SQLAlchemy + aiomysql）"""
    from web_infra.capabilities.db.mysql_config import MySQLConfig
    from web_infra.capabilities.db.mysql_database import MySQLDatabase
    from web_infra.capabilities.db.mysql_connection_settings import MySQLConnectionSettings

    # isolation_level 不属于连接设置，单独透传给 MySQLConfig（None/DEFAULT 不注入，让数据库用默认）
    isolation_level = params.get("isolation_level")
    settings = MySQLConnectionSettings(
        **{k: v for k, v in params.items() if v is not None and k not in ("instances", "datasource_name", "isolation_level")}
    )
    config = MySQLConfig(
        settings=settings,
        datasource_name=params.get("datasource_name") or "default",
        isolation_level=isolation_level,
    )
    return MySQLDatabase(config)


def _sqlite_factory(params: dict[str, Any]) -> DatabaseFactoryInterface:
    """内置 sqlite：SQLite 同步会话工厂（轻量/测试场景）"""
    from web_infra.capabilities.db.sqlite_session_factory import SqliteSessionFactory

    return SqliteSessionFactory(db_path=params.get("path") or ":memory:")  # type: ignore[return-value]  # sqlite 同步会话与异步 DatabaseFactoryInterface 契约并存（轻量/测试场景）


# 内置数据库条目（模块导入即注册，幂等；落框架命名空间，受保护）
DatabaseRegistry.register("mysql", _mysql_factory, namespace=DatabaseRegistry.FRAMEWORK_NAMESPACE)
DatabaseRegistry.register("sqlite", _sqlite_factory, namespace=DatabaseRegistry.FRAMEWORK_NAMESPACE)
