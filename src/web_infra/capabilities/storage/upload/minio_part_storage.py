"""
MinIO 分片存储

@Author: 花海
@Date: 2026/08/14 19:30
@Description: 基于 MinIO 的分片存储（规范 §22.4 生产实现）：
              分片作为独立对象 `{upload_id}/part_{n}` 存储，合并用 S3 compose_object
              （服务端合并，不占客户端内存），合并后清理分片对象。
              延迟导入 minio SDK（minio>=7.2 核心依赖）。
"""
from __future__ import annotations

import asyncio
import io
from typing import Any

from web_infra.capabilities.storage.minio_storage_config import MinioStorageConfig


class MinioPartStorage:
    """MinIO 分片存储（S3 分段/分片对象 + compose 合并）"""

    def __init__(self, config: MinioStorageConfig, bucket: str = "") -> None:
        """初始化分片存储。

        :param config: MinIO 客户端配置
        :param bucket: 分片与合并对象所在桶（默认取配置默认桶）
        """
        from minio import Minio  # 延迟导入

        self._config = config
        self._bucket = bucket or config.default_bucket
        self._client = Minio(
            config.endpoint,
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=config.secure,
        )

    def _part_key(self, upload_id: str, part_number: int) -> str:
        """分片对象 Key"""
        return f"{upload_id}/part_{part_number}"

    async def save_part(self, upload_id: str, part_number: int, data: bytes) -> None:
        """保存分片（同分片重传覆盖，幂等）"""
        def _put() -> None:
            self._client.put_object(
                self._bucket,
                self._part_key(upload_id, part_number),
                io.BytesIO(data),
                length=len(data),
            )

        await asyncio.to_thread(_put)

    async def list_parts(self, upload_id: str) -> list[int]:
        """列出已存在分片序号（升序，断点续传依据）"""
        def _list() -> list[int]:
            parts = []
            for obj in self._client.list_objects(self._bucket, prefix=f"{upload_id}/", recursive=True):
                name = obj.object_name
                if name is None or "/part_" not in name:
                    continue
                try:
                    parts.append(int(name.rsplit("part_", 1)[1]))
                except ValueError:
                    continue
            return sorted(parts)

        return await asyncio.to_thread(_list)

    async def read_part(self, upload_id: str, part_number: int) -> bytes:
        """读取单个分片内容（MD5 合并校验）"""
        def _read() -> bytes:
            response = self._client.get_object(self._bucket, self._part_key(upload_id, part_number))
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(_read)

    async def merge(self, upload_id: str, object_key: str) -> int:
        """S3 compose 服务端合并分片对象，返回合并后大小（字节）；合并后清理分片"""
        def _compose() -> int:
            from minio.compose import SourceObject  # 延迟导入  # type: ignore[reportMissingImports]

            parts = self._list_parts_sync(upload_id)
            if not parts:
                raise RuntimeError(f"分片为空，无法合并: {upload_id}")
            sources = [SourceObject(self._bucket, self._part_key(upload_id, n)) for n in parts]
            self._client.compose_object(self._bucket, object_key, sources)
            # compose 结果无大小字段，合并后 stat 对象取实际大小（供完整性校验）
            info = self._client.stat_object(self._bucket, object_key)
            size = info.size
            if size is None:
                raise RuntimeError(f"合并对象大小未知: {object_key}")
            self._remove_task_sync(upload_id)
            return int(size)

        return await asyncio.to_thread(_compose)

    async def remove_task(self, upload_id: str) -> None:
        """清理任务全部分片对象"""
        await asyncio.to_thread(self._remove_task_sync, upload_id)

    # ------------------------------------------------------------------
    # 内部（同步辅助，供 asyncio.to_thread 调用）
    # ------------------------------------------------------------------

    def _list_parts_sync(self, upload_id: str) -> list[int]:
        """同步列出分片序号"""
        parts = []
        for obj in self._client.list_objects(self._bucket, prefix=f"{upload_id}/", recursive=True):
            name = obj.object_name
            if name is None or "/part_" not in name:
                continue
            try:
                parts.append(int(name.rsplit("part_", 1)[1]))
            except ValueError:
                continue
        return sorted(parts)

    def _remove_task_sync(self, upload_id: str) -> None:
        """同步删除任务分片对象"""
        names = [
            obj.object_name
            for obj in self._client.list_objects(self._bucket, prefix=f"{upload_id}/", recursive=True)
            if obj.object_name is not None
        ]
        for name in names:
            self._client.remove_object(self._bucket, name)
