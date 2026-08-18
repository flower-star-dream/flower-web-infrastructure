"""
对象存储模块

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 对象存储统一抽象接口与实现聚合导出，遵循规范 §22（文件与对象存储）。
              抽象接口屏蔽 MinIO/云 OSS/S3 差异；本地实现用于单机/测试场景。
"""
from web_infra.capabilities.storage.storage_config import StorageConfig
from web_infra.capabilities.storage.object_storage_interface import ObjectStorageInterface
from web_infra.capabilities.storage.local_object_storage import LocalObjectStorage
from web_infra.capabilities.storage.minio_storage_config import MinioStorageConfig
from web_infra.capabilities.storage.minio_storage import MinioObjectStorage
from web_infra.capabilities.storage.object_storage_registry import ObjectStorageRegistry
from web_infra.capabilities.storage.upload import (
    UploadStatus,
    UploadTask,
    UploadStoreInterface,
    InMemoryUploadStore,
    PartStorageInterface,
    LocalPartStorage,
    MinioPartStorage,
    MultipartUploadService,
)

__all__ = [
    "StorageConfig",
    "ObjectStorageInterface",
    "LocalObjectStorage",
    "MinioStorageConfig",
    "MinioObjectStorage",
    "ObjectStorageRegistry",
    "UploadStatus",
    "UploadTask",
    "UploadStoreInterface",
    "InMemoryUploadStore",
    "PartStorageInterface",
    "LocalPartStorage",
    "MinioPartStorage",
    "MultipartUploadService",
]
