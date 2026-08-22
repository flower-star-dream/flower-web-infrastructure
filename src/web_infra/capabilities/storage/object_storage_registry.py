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

from typing import Callable

from web_infra.capabilities.storage.object_storage_interface import ObjectStorageInterface
from web_infra.core.spi import SpiRegistry
from web_infra.infra.config import Settings

#: 对象存储工厂签名：入参装配配置（Settings），返回对象存储实现
ObjectStorageFactory = Callable[[Settings], ObjectStorageInterface]


class ObjectStorageRegistry(SpiRegistry):
    """对象存储注册表（SpiRegistry 基类：命名空间隔离 + 内置默认保护；同名覆盖默认拒绝）"""

    @classmethod
    def create(cls, name: str, settings: Settings) -> ObjectStorageInterface:
        """按名实例化存储后端；未注册抛 KeyError"""
        return cls.get(name)(settings)


def _local_storage_factory(settings: Settings) -> ObjectStorageInterface:
    """内置 local：本地文件系统存储（单机/测试场景）"""
    from web_infra.capabilities.storage.local_object_storage import LocalObjectStorage
    from web_infra.capabilities.storage.storage_config import StorageConfig

    return LocalObjectStorage(StorageConfig(base_dir=settings.get("app.storage.base_dir")))


def _minio_storage_factory(settings: Settings) -> ObjectStorageInterface:
    """内置 minio：MinIO 对象存储（多实例/微服务场景）"""
    from web_infra.capabilities.storage.minio_storage import MinioObjectStorage
    from web_infra.capabilities.storage.minio_storage_config import MinioStorageConfig

    config = MinioStorageConfig(
        **{
            field: settings.get(f"app.storage.minio.{field}")
            for field in MinioStorageConfig.model_fields
            if settings.get(f"app.storage.minio.{field}") is not None
        }
    )
    return MinioObjectStorage(config)


# 内置后端条目（模块导入即注册，幂等；落框架命名空间，受保护）
ObjectStorageRegistry.register("local", _local_storage_factory, namespace=ObjectStorageRegistry.FRAMEWORK_NAMESPACE)
ObjectStorageRegistry.register("minio", _minio_storage_factory, namespace=ObjectStorageRegistry.FRAMEWORK_NAMESPACE)
