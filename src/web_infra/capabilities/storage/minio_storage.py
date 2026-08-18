"""
MinIO 对象存储

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 基于 minio SDK 的对象存储实现，遵循规范 §22（私有读写 + 签名 URL + 防盗链）。
              实现 ObjectStorageInterface 抽象，供多实例/微服务场景使用；依赖 minio 包（延迟导入）。
"""
from __future__ import annotations

import asyncio
import io
from datetime import timedelta
from typing import Callable

from web_infra.infra.context import RequestContext
from web_infra.infra.monitoring.storage_metrics import StorageMetrics
from web_infra.capabilities.storage.minio_storage_config import MinioStorageConfig
from web_infra.capabilities.storage.object_storage_interface import ObjectStorageInterface

# 存储实现名（低基数标签，对应 app.storage.type）
_STORAGE_NAME = "minio"


class MinioObjectStorage(ObjectStorageInterface):
    """MinIO 对象存储实现（实现 ObjectStorageInterface 抽象）"""

    def __init__(self, config: MinioStorageConfig) -> None:
        from minio import Minio  # 延迟导入，避免强制依赖

        self.config = config
        self._client = Minio(
            config.endpoint,
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=config.secure,
        )

    def _resolve_bucket(self, bucket: str) -> str:
        """解析桶名（未指定时使用默认桶）"""
        return bucket or self.config.default_bucket

    async def put(self, bucket: str, key: str, data: bytes, content_type: str | None = None) -> None:
        def _put() -> None:
            stream = io.BytesIO(data)
            self._client.put_object(
                self._resolve_bucket(bucket),
                key,
                stream,
                length=len(data),
                content_type=content_type or "application/octet-stream",
            )

        await asyncio.to_thread(_put)
        StorageMetrics.record_operation(_STORAGE_NAME, "put", bytes_count=len(data))

    @staticmethod
    def _run_owner_validator(key: str, owner: str | None, owner_validator: Callable[[str, str | None, str | None], None] | None) -> None:
        """执行属主校验钩子（规范 §22.4）：业务注入时在下载/删除前调用，current_user 取自请求上下文"""
        if owner_validator is not None:
            owner_validator(key, owner, RequestContext.get_user_id())

    async def get(
        self,
        bucket: str,
        key: str,
        *,
        owner: str | None = None,
        owner_validator: Callable[[str, str | None, str | None], None] | None = None,
    ) -> bytes | None:
        """下载对象，不存在返回 None（owner/owner_validator 语义见 ObjectStorageInterface，规范 §22.4）"""
        self._run_owner_validator(key, owner, owner_validator)

        def _get() -> bytes | None:
            try:
                response = self._client.get_object(self._resolve_bucket(bucket), key)
                try:
                    return response.read()
                finally:
                    response.close()
            except Exception:
                # 对象不存在或读取失败，返回 None（真实场景应结合错误码细化处理）
                return None

        data = await asyncio.to_thread(_get)
        StorageMetrics.record_operation(_STORAGE_NAME, "get", bytes_count=len(data) if data else 0)
        return data

    async def delete(
        self,
        bucket: str,
        key: str,
        *,
        owner: str | None = None,
        owner_validator: Callable[[str, str | None, str | None], None] | None = None,
    ) -> None:
        """删除对象（owner/owner_validator 语义见 ObjectStorageInterface，规范 §22.4 防越权删除）"""
        self._run_owner_validator(key, owner, owner_validator)

        def _delete() -> None:
            self._client.remove_object(self._resolve_bucket(bucket), key)

        await asyncio.to_thread(_delete)
        StorageMetrics.record_operation(_STORAGE_NAME, "delete")

    async def exists(self, bucket: str, key: str) -> bool:
        def _exists() -> bool:
            try:
                self._client.stat_object(self._resolve_bucket(bucket), key)
                return True
            except Exception:
                return False

        result = await asyncio.to_thread(_exists)
        StorageMetrics.record_operation(_STORAGE_NAME, "exists")
        return result

    async def presign_url(self, bucket: str, key: str, expires: int | None = None) -> str:
        def _presign() -> str:
            ttl = expires or self.config.presign_expires
            return self._client.presigned_get_object(
                self._resolve_bucket(bucket),
                key,
                expires=timedelta(seconds=ttl),
            )

        return await asyncio.to_thread(_presign)
