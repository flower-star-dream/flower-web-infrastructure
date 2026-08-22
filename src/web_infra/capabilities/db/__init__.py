"""
数据库模块

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 数据库相关能力统一模块，遵循规范 §3（SPI）、§10（数据访问）、§12.3（分页）、§14.1（连接池）。
              - 通用数据库交互接口：DatabaseSessionInterface / DatabaseFactoryInterface（SPI，用户可扩展 PG 等）
              - MongoDB 交互接口：MongoSessionInterface / MongoDatabaseFactoryInterface + MongoDatabaseRegistry
                （SPI，内置 beanie 默认实现 Beanie + PyMongo）
              - 默认实现：MySQLDatabase（SQLAlchemy + aiomysql）、MongoDatabase（Beanie + PyMongo）
              - 其他实现：MongoDBConfig、RedisConfig（Redis 本质为数据库，故归入 db）、SQLite 同步参考
              - session_utils：长耗时外部调用前释放连接
"""
from importlib import import_module
from typing import TYPE_CHECKING

from web_infra.capabilities.db.database_config import DatabaseConfig
from web_infra.capabilities.db.page_query import PageQuery
from web_infra.capabilities.db.sqlite_session import SqliteSession
from web_infra.capabilities.db.sqlite_session_factory import SqliteSessionFactory
from web_infra.capabilities.db.database_session_interface import DatabaseSessionInterface
from web_infra.capabilities.db.database_factory_interface import DatabaseFactoryInterface
from web_infra.capabilities.db.database_registry import DatabaseRegistry
from web_infra.capabilities.db.mongo_session_interface import MongoSessionInterface
from web_infra.capabilities.db.mongo_database_factory_interface import MongoDatabaseFactoryInterface
from web_infra.capabilities.db.mongo_database_registry import MongoDatabaseRegistry
from web_infra.capabilities.db.mysql_connection_settings import MySQLConnectionSettings
from web_infra.capabilities.db.session_utils import (
    connection_released,
    release_session_connection,
)
from web_infra.capabilities.db.tenant_guard import TenantGuard
from web_infra.capabilities.db.database_router import DatabaseRouterInterface, TenantDatabaseRouter
from web_infra.capabilities.db.session_scope_mixin import SessionScopeMixin
from web_infra.capabilities.db.session_dependency import provide_db_session
from web_infra.capabilities.db.transaction_propagation import (
    IsolationLevel,
    Propagation,
    TransactionPropagationError,
)

if TYPE_CHECKING:
    from web_infra.capabilities.db.mysql_base import Base
    from web_infra.capabilities.db.mysql_config import MySQLConfig
    from web_infra.capabilities.db.mysql_database import MySQLDatabase
    from web_infra.capabilities.db.sqlalchemy_database_session import SqlAlchemyDatabaseSession
    from web_infra.capabilities.db.mongodb_config import MongoDBConfig
    from web_infra.capabilities.db.beanie_mongo_session import BeanieMongoSession
    from web_infra.capabilities.db.mongo_database import MongoDatabase
    from web_infra.capabilities.db.redis_config import RedisConfig
    from web_infra.capabilities.db.redis_cache_backend import RedisCacheBackend
    from web_infra.capabilities.db.tenant_aware_mixin import TenantAwareMixin
    from web_infra.capabilities.db.tenant_query_filter import TenantQueryFilter
    from web_infra.capabilities.db.database_manager import DatabaseManager

# 惰性导出名 -> 定义子模块（依赖 sqlalchemy/redis/mongo；最小安装未装对应依赖时，
# 仅首次访问该名字才抛 ImportError，`import web_infra` / `from web_infra.capabilities.db import 非惰性名` 不触发）
_LAZY_EXPORTS: dict[str, str] = {
    "Base": "web_infra.capabilities.db.mysql_base",
    "MySQLConfig": "web_infra.capabilities.db.mysql_config",
    "MySQLDatabase": "web_infra.capabilities.db.mysql_database",
    "SqlAlchemyDatabaseSession": "web_infra.capabilities.db.sqlalchemy_database_session",
    "MongoDBConfig": "web_infra.capabilities.db.mongodb_config",
    "BeanieMongoSession": "web_infra.capabilities.db.beanie_mongo_session",
    "MongoDatabase": "web_infra.capabilities.db.mongo_database",
    "RedisConfig": "web_infra.capabilities.db.redis_config",
    "RedisCacheBackend": "web_infra.capabilities.db.redis_cache_backend",
    "TenantAwareMixin": "web_infra.capabilities.db.tenant_aware_mixin",
    "TenantQueryFilter": "web_infra.capabilities.db.tenant_query_filter",
    "DatabaseManager": "web_infra.capabilities.db.database_manager",
}


def __getattr__(name: str) -> object:
    """惰性导出：首次访问时导入对应子模块并缓存到模块命名空间（避免重复导入）。

    :param name: 访问的属性名
    :return: 子模块中同名导出对象
    :raises AttributeError: 未匹配的属性名
    """
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is not None:
        value = getattr(import_module(module_name), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "DatabaseConfig",
    "PageQuery",
    "SqliteSession",
    "SqliteSessionFactory",
    # 通用数据库交互接口（SPI）
    "DatabaseSessionInterface",
    "DatabaseFactoryInterface",
    "DatabaseRegistry",
    # MongoDB 交互接口（SPI）
    "MongoSessionInterface",
    "MongoDatabaseFactoryInterface",
    "MongoDatabaseRegistry",
    "SessionScopeMixin",
    "provide_db_session",
    # 事务传播（无第三方依赖，可安全导入 *）
    "Propagation",
    "IsolationLevel",
    "TransactionPropagationError",
    # MySQL 连接配置（仅依赖核心 pydantic，可安全导入 *）
    "MySQLConnectionSettings",
    # 会话工具
    "release_session_connection",
    "connection_released",
    # 多租户（无第三方依赖的部分）
    "TenantGuard",
    "DatabaseRouterInterface",
    "TenantDatabaseRouter",
]

# 说明：依赖 sqlalchemy/redis/mongo 的实现（Base / MySQLConfig / MySQLDatabase / SqlAlchemyDatabaseSession /
# MongoDBConfig / BeanieMongoSession / MongoDatabase / RedisConfig / RedisCacheBackend / TenantAwareMixin /
# TenantQueryFilter / DatabaseManager）不在 __all__ 中——保证 `from web_infra.capabilities.db import *` 在最小安装
# （未装三者）下不触发惰性导入报错；需使用时请显式导入（如 `from web_infra.capabilities.db import MySQLConfig`），
# 经模块 __getattr__ 惰性加载。
# 已安装对应依赖（非最小安装）时，下方 _extend_all_with_installed() 会自动将这些名字纳入 __all__，
# 使 `from web_infra.capabilities.db import *` 全量导出。

# 惰性导出名 -> 其依赖的第三方包（已安装时该名字纳入 __all__）
_LAZY_ALL_REQUIRES: dict[str, tuple[str, ...]] = {
    "Base": ("sqlalchemy",),
    "MySQLConfig": ("sqlalchemy",),
    "MySQLDatabase": ("sqlalchemy",),
    "SqlAlchemyDatabaseSession": ("sqlalchemy",),
    "MongoDBConfig": ("pymongo", "beanie"),
    "BeanieMongoSession": ("pymongo", "beanie"),
    "MongoDatabase": ("pymongo", "beanie"),
    "RedisConfig": ("redis",),
    "RedisCacheBackend": ("redis",),
    "TenantAwareMixin": ("sqlalchemy",),
    "TenantQueryFilter": ("sqlalchemy",),
    "DatabaseManager": ("sqlalchemy",),
}


def _extend_all_with_installed() -> None:
    """按已安装的可选依赖动态扩展 __all__（import * 全量导出）。

    最小安装时惰性名不进 __all__，`import *` 不触发惰性导入；安装对应 extras 后自动纳入。
    检测用 importlib.util.find_spec（不实际导入，避免触发惰性加载）。
    """
    import importlib.util

    for name, packages in _LAZY_ALL_REQUIRES.items():
        try:
            installed = all(importlib.util.find_spec(pkg) is not None for pkg in packages)
        except (ImportError, ValueError):
            installed = False
        if installed and name not in __all__:
            __all__.append(name)


_extend_all_with_installed()
