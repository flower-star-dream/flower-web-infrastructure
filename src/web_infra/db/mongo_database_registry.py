"""
MongoDB 数据库注册表

@Author: 花海
@Date: 2026/08/18 10:00
@Description: MongoDB 数据库 SPI 注册表：按 type 名注册/查询 MongoDatabaseFactoryInterface 工厂，
              装配期（app.mongo.type）按名实例化；
              内置 beanie 条目（MongoDB 默认实现，Beanie + PyMongo），用户自定义文档数据库实现
              经 register 注册后即可接入 create_app（app.mongo.enabled=true 时装配），无需改动框架装配代码；
              未注册的 mongo.type 装配期快速失败（ConfigError）。
"""
from __future__ import annotations

from threading import Lock
from typing import Any, Callable, ClassVar

from web_infra.db.mongo_database_factory_interface import MongoDatabaseFactoryInterface

#: MongoDB 数据库工厂签名：入参实例连接参数（app.mongo 段，排除 enabled/type），
#: 返回 MongoDB 数据库工厂实现（MongoDatabaseFactoryInterface）
MongoDatabaseFactory = Callable[[dict[str, Any]], MongoDatabaseFactoryInterface]


class MongoDatabaseRegistry:
    """MongoDB 数据库注册表（类级注册，全局装配；同名覆盖）"""

    _factories: ClassVar[dict[str, MongoDatabaseFactory]] = {}
    _lock = Lock()

    @classmethod
    def register(cls, name: str, factory: MongoDatabaseFactory) -> None:
        """注册 MongoDB 数据库工厂（同名覆盖）。

        :param name: type 名（与 yml app.mongo.type 匹配）
        :param factory: 工厂，入参实例连接参数 dict，返回 MongoDatabaseFactoryInterface 实现
        """
        with cls._lock:
            cls._factories[name] = factory

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销 MongoDB 数据库（不存在时静默）"""
        with cls._lock:
            cls._factories.pop(name, None)

    @classmethod
    def get(cls, name: str) -> MongoDatabaseFactory:
        """按名查询工厂；未注册抛 KeyError（装配期由 create_app 捕获转 ConfigError）"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory

    @classmethod
    def create(cls, name: str, params: dict[str, Any]) -> MongoDatabaseFactoryInterface:
        """按名实例化 MongoDB 数据库；未注册抛 KeyError"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory(params)

    @classmethod
    def registered_names(cls) -> list[str]:
        """已注册 MongoDB 数据库名清单"""
        with cls._lock:
            return list(cls._factories)


def _beanie_factory(params: dict[str, Any]) -> MongoDatabaseFactoryInterface:
    """内置 beanie：MongoDB 默认实现（Beanie + PyMongo AsyncMongoClient）"""
    from web_infra.db.mongodb_config import MongoDBConfig
    from web_infra.db.mongo_database import MongoDatabase

    config = MongoDBConfig(
        **{k: v for k, v in params.items() if v is not None and k not in ("type", "enabled")}
    )
    return MongoDatabase(config)


# 内置 MongoDB 数据库条目（模块导入即注册，幂等）
MongoDatabaseRegistry.register("beanie", _beanie_factory)
