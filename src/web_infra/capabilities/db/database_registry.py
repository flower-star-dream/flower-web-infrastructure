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

from threading import Lock
from typing import Any, Callable, ClassVar

from web_infra.capabilities.db.database_factory_interface import DatabaseFactoryInterface

#: 数据库工厂签名：入参实例连接参数（单源取 app.db.<type> 段，混合多源取 app.db.instances 实例项），
#: 返回数据库工厂实现（DatabaseFactoryInterface，可含 session_factory/orm_session 等扩展能力）
DatabaseFactory = Callable[[dict[str, Any]], DatabaseFactoryInterface]


class DatabaseRegistry:
    """数据库注册表（类级注册，全局装配；同名覆盖）"""

    _factories: ClassVar[dict[str, DatabaseFactory]] = {}
    _lock = Lock()

    @classmethod
    def register(cls, name: str, factory: DatabaseFactory) -> None:
        """注册数据库工厂（同名覆盖）。

        :param name: type 名（与 yml app.db.type 或 app.db.instances 实例 type 匹配）
        :param factory: 工厂，入参实例连接参数 dict，返回 DatabaseFactoryInterface 实现
        """
        with cls._lock:
            cls._factories[name] = factory

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销数据库（不存在时静默）"""
        with cls._lock:
            cls._factories.pop(name, None)

    @classmethod
    def get(cls, name: str) -> DatabaseFactory:
        """按名查询工厂；未注册抛 KeyError（装配期由 create_app 捕获转 ConfigError）"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory

    @classmethod
    def create(cls, name: str, params: dict[str, Any]) -> DatabaseFactoryInterface:
        """按名实例化数据库；未注册抛 KeyError"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory(params)

    @classmethod
    def registered_names(cls) -> list[str]:
        """已注册数据库名清单"""
        with cls._lock:
            return list(cls._factories)


def _mysql_factory(params: dict[str, Any]) -> DatabaseFactoryInterface:
    """内置 mysql：MySQL 数据库工厂（SQLAlchemy + aiomysql）"""
    from web_infra.capabilities.db.mysql_config import MySQLConfig
    from web_infra.capabilities.db.mysql_database import MySQLDatabase
    from web_infra.capabilities.db.mysql_connection_settings import MySQLConnectionSettings

    settings = MySQLConnectionSettings(
        **{k: v for k, v in params.items() if v is not None and k not in ("instances", "datasource_name")}
    )
    return MySQLDatabase(MySQLConfig(settings=settings, datasource_name=params.get("datasource_name") or "default"))


def _sqlite_factory(params: dict[str, Any]) -> DatabaseFactoryInterface:
    """内置 sqlite：SQLite 同步会话工厂（轻量/测试场景）"""
    from web_infra.capabilities.db.sqlite_session_factory import SqliteSessionFactory

    return SqliteSessionFactory(db_path=params.get("path") or ":memory:")  # type: ignore[return-value]  # sqlite 同步会话与异步 DatabaseFactoryInterface 契约并存（轻量/测试场景）


# 内置数据库条目（模块导入即注册，幂等）
DatabaseRegistry.register("mysql", _mysql_factory)
DatabaseRegistry.register("sqlite", _sqlite_factory)
