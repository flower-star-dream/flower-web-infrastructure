"""
对象存储注册表

@Author: 花海
@Date: 2026/08/17 17:00
@Description: 对象存储 SPI 注册表：按 type 名注册/查询 ObjectStorageInterface 工厂，
              装配期（app.storage.type）按名实例化；内置 local/minio 条目，
              用户自定义存储后端（云 OSS/S3 等）经 register 注册后即可接入 create_app，
              无需改动框架装配代码；未注册的 type 装配期快速失败（ConfigError）。
"""
from __future__ import annotations

from threading import Lock
from typing import Callable, ClassVar

from web_infra.config import Settings
from web_infra.storage.object_storage_interface import ObjectStorageInterface

#: 对象存储工厂签名：入参装配配置（Settings），返回对象存储实现
ObjectStorageFactory = Callable[[Settings], ObjectStorageInterface]


class ObjectStorageRegistry:
    """对象存储注册表（类级注册，全局装配；同名覆盖）"""

    _factories: ClassVar[dict[str, ObjectStorageFactory]] = {}
    _lock = Lock()

    @classmethod
    def register(cls, name: str, factory: ObjectStorageFactory) -> None:
        """注册存储后端工厂（同名覆盖）。

        :param name: type 名（与 yml app.storage.type 匹配）
        :param factory: 工厂，入参 Settings，返回 ObjectStorageInterface 实现
        """
        with cls._lock:
            cls._factories[name] = factory

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销后端（不存在时静默）"""
        with cls._lock:
            cls._factories.pop(name, None)

    @classmethod
    def get(cls, name: str) -> ObjectStorageFactory:
        """按名查询工厂；未注册抛 KeyError（装配期由 create_app 捕获转 ConfigError）"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory

    @classmethod
    def create(cls, name: str, settings: Settings) -> ObjectStorageInterface:
        """按名实例化存储后端；未注册抛 KeyError"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory(settings)

    @classmethod
    def registered_names(cls) -> list[str]:
        """已注册后端名清单"""
        with cls._lock:
            return list(cls._factories)


def _local_storage_factory(settings: Settings) -> ObjectStorageInterface:
    """内置 local：本地文件系统存储（单机/测试场景）"""
    from web_infra.storage.local_object_storage import LocalObjectStorage
    from web_infra.storage.storage_config import StorageConfig

    return LocalObjectStorage(StorageConfig(base_dir=settings.get("app.storage.base_dir")))


def _minio_storage_factory(settings: Settings) -> ObjectStorageInterface:
    """内置 minio：MinIO 对象存储（多实例/微服务场景）"""
    from web_infra.storage.minio_storage import MinioObjectStorage
    from web_infra.storage.minio_storage_config import MinioStorageConfig

    config = MinioStorageConfig(
        **{
            field: settings.get(f"app.storage.minio.{field}")
            for field in MinioStorageConfig.model_fields
            if settings.get(f"app.storage.minio.{field}") is not None
        }
    )
    return MinioObjectStorage(config)


# 内置后端条目（模块导入即注册，幂等）
ObjectStorageRegistry.register("local", _local_storage_factory)
ObjectStorageRegistry.register("minio", _minio_storage_factory)
