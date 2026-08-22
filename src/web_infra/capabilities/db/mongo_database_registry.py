"""
MongoDB 数据库注册表

@Author: 花海
@Date: 2026/08/18 10:00
@Description: MongoDB 数据库 SPI 注册表：按 type 名注册/查询 MongoDatabaseFactoryInterface 工厂，
              装配期（app.mongo.type）按名实例化；
              内置 beanie 条目（MongoDB 默认实现，Beanie + PyMongo），用户自定义文档数据库实现
              经 register 注册后即可接入 create_app（app.mongo.enabled=true 时装配），无需改动框架装配代码；
              未注册的 mongo.type 装配期快速失败（ConfigError）。
              继承 SpiRegistry 基类：内置默认落框架命名空间（受保护），用户同名覆盖经默认命名空间解析。
"""
from __future__ import annotations

from typing import Any, Callable

from web_infra.capabilities.db.mongo_database_factory_interface import MongoDatabaseFactoryInterface
from web_infra.core.spi import SpiRegistry

#: MongoDB 数据库工厂签名：入参实例连接参数（app.mongo 段，排除 enabled/type），
#: 返回 MongoDB 数据库工厂实现（MongoDatabaseFactoryInterface）
MongoDatabaseFactory = Callable[[dict[str, Any]], MongoDatabaseFactoryInterface]


class MongoDatabaseRegistry(SpiRegistry):
    """MongoDB 数据库注册表（类级注册，全局装配；同名覆盖）"""

    @classmethod
    def create(cls, name: str, params: dict[str, Any]) -> MongoDatabaseFactoryInterface:
        """按名实例化 MongoDB 数据库；未注册抛 KeyError"""
        return cls.get(name)(params)


def _beanie_factory(params: dict[str, Any]) -> MongoDatabaseFactoryInterface:
    """内置 beanie：MongoDB 默认实现（Beanie + PyMongo AsyncMongoClient）"""
    from web_infra.capabilities.db.mongodb_config import MongoDBConfig
    from web_infra.capabilities.db.mongo_database import MongoDatabase

    config = MongoDBConfig(
        **{k: v for k, v in params.items() if v is not None and k not in ("type", "enabled")}
    )
    return MongoDatabase(config)


# 内置 MongoDB 数据库条目（模块导入即注册，幂等）
MongoDatabaseRegistry.register(
    "beanie", _beanie_factory, namespace=MongoDatabaseRegistry.FRAMEWORK_NAMESPACE
)
