"""
本地文件对象存储

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 本地文件对象存储参考实现（单机/测试场景，规范 §22）。
              - 私有文件签名 URL（规范 §22.3）：presign_url 返回带过期时间戳与 HMAC 签名的 URL；
              - 属主校验钩子（规范 §22.4）：get/delete 支持业务注入 owner_validator 防水平越权；
              生产环境必须接入对象存储并遵守私有读写 + 签名 URL。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
from typing import Callable

from web_infra.context import RequestContext
from web_infra.monitoring.storage_metrics import StorageMetrics
from web_infra.storage.object_storage_interface import ObjectStorageInterface
from web_infra.storage.storage_config import StorageConfig

# 存储实现名（低基数标签，对应 app.storage.type）
_STORAGE_NAME = "local"

# 签名 URL 密钥（规范 §22.3 私有文件签名 URL）：生产环境必须经环境变量注入，
# 本地默认值仅用于开发/测试场景
_LOCAL_PRESIGN_SECRET = os.getenv("LOCAL_STORAGE_PRESIGN_SECRET", "local-presign-secret")


class LocalObjectStorage(ObjectStorageInterface):
    """本地文件对象存储参考实现（单机/测试场景）

    注意：仅适用于单体或本地开发；生产环境必须接入对象存储并遵守私有读写 + 签名 URL。
    """

    def __init__(self, config: StorageConfig | None = None) -> None:
        self.config = config or StorageConfig()
        os.makedirs(self.config.base_dir, exist_ok=True)

    def _path(self, bucket: str, key: str) -> str:
        """计算对象在本地磁盘的完整路径"""
        return os.path.join(self.config.base_dir, bucket, key)

    def _sign(self, bucket: str, key: str, expires: int) -> str:
        """计算签名 URL 的 HMAC-SHA256 签名（bucket/key/expires 参与计算，防止 URL 被篡改，规范 §22.3）"""
        message = f"{bucket}/{key}:{expires}"
        return hmac.new(_LOCAL_PRESIGN_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _run_owner_validator(key: str, owner: str | None, owner_validator: Callable[[str, str | None, str | None], None] | None) -> None:
        """执行属主校验钩子（规范 §22.4）：业务注入时在下载/删除前调用，current_user 取自请求上下文"""
        if owner_validator is not None:
            owner_validator(key, owner, RequestContext.get_user_id())

    async def put(self, bucket: str, key: str, data: bytes, content_type: str | None = None) -> None:
        def _write() -> None:
            path = self._path(bucket, key)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)

        await asyncio.to_thread(_write)
        StorageMetrics.record_operation(_STORAGE_NAME, "put", bytes_count=len(data))

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

        def _read() -> bytes | None:
            path = self._path(bucket, key)
            if not os.path.exists(path):
                return None
            with open(path, "rb") as f:
                return f.read()

        data = await asyncio.to_thread(_read)
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
            path = self._path(bucket, key)
            if os.path.exists(path):
                os.remove(path)

        await asyncio.to_thread(_delete)
        StorageMetrics.record_operation(_STORAGE_NAME, "delete")

    async def exists(self, bucket: str, key: str) -> bool:
        result = await asyncio.to_thread(lambda: os.path.exists(self._path(bucket, key)))
        StorageMetrics.record_operation(_STORAGE_NAME, "exists")
        return result

    async def presign_url(self, bucket: str, key: str, expires: int | None = None) -> str:
        """生成私有文件签名 URL（规范 §22.3）。

        本地实现返回 `<本地路径>?expires=<unix 过期时间戳>&signature=<HMAC-SHA256 签名>`，
        携带过期时间戳与签名（bucket/key/expires 参与 HMAC 计算防篡改）；真实对象存储
        （MinIO/OSS/S3）返回其 SDK 签名 URL。expires 缺省使用 StorageConfig.presign_expires（≤10min）。
        下载侧对签名/过期的校验由业务按需处理（本参考实现不在 get() 中强制校验，
        生产环境请接入对象存储的签名 URL 能力）。
        """
        ttl = expires or self.config.presign_expires
        exp = int(time.time()) + int(ttl)
        signature = self._sign(bucket, key, exp)
        return f"{self._path(bucket, key)}?expires={exp}&signature={signature}"
