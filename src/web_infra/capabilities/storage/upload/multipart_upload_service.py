"""
分片上传服务

@Author: 花海
@Date: 2026/08/14 19:30
@Description: 分片上传/断点续传服务（规范 §22.4）：
              大文件（>50MB）必须分片：初始化上传任务 -> 逐片上传（重试幂等）-> 合并校验（大小）-> 清理；
              断点续传通过 list_uploaded_parts 定位已传分片。
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from web_infra.capabilities.storage.upload.file_type_validator import FileTypeValidator
from web_infra.capabilities.storage.upload.upload_status import UploadStatus
from web_infra.capabilities.storage.upload.upload_task import UploadTask


class MultipartUploadService:
    """分片上传服务（初始化 / 逐片上传 / 断点续传 / 合并校验 / 清理）"""

    # 默认分片大小 5MB（规范未规定具体数值，5MB 为常见默认）
    DEFAULT_CHUNK_SIZE = 5 * 1024 * 1024
    # 大文件阈值 50MB：超过必须分片（规范 §22.4）
    LARGE_FILE_THRESHOLD = 50 * 1024 * 1024

    def __init__(
        self,
        store: Any,
        part_storage: Any,
        *,
        default_chunk_size: int | None = None,
        file_type_validator: FileTypeValidator | None = None,
        max_upload_size: int | None = None,
    ) -> None:
        """初始化上传服务。

        :param store: 上传任务存储（UploadStoreInterface）
        :param part_storage: 分片存储（PartStorageInterface，本地/MinIO 双实现）
        :param default_chunk_size: 默认分片大小（字节，默认 5MB）
        :param file_type_validator: 文件类型校验器（规范 §22.2，默认内置白名单）
        :param max_upload_size: 上传大小上限（字节，None 表示不限制；规范 §22.2 大小上限）
        """
        self._store = store
        self._part_storage = part_storage
        self._default_chunk_size = default_chunk_size or self.DEFAULT_CHUNK_SIZE
        self._validator = file_type_validator or FileTypeValidator()
        self._max_upload_size = max_upload_size

    async def initialize(self, file_name: str, file_size: int, chunk_size: int | None = None) -> UploadTask:
        """初始化上传任务（规范 §22.4：初始化上传任务）。

        :param file_name: 原始文件名（校验后缀白名单，规范 §22.2）
        :param file_size: 文件总大小（字节）
        :param chunk_size: 分片大小（字节，缺省默认 5MB）
        :return: 上传任务（含 upload_id，断点续传定位依据）
        :raises ValueError: 文件大小非正、超过上传大小上限、大文件未分片或文件类型不在白名单
        """
        if file_size <= 0:
            raise ValueError("文件大小必须大于 0")
        # 上传大小上限校验（规范 §22.2：超过上限拒绝上传）
        if self._max_upload_size is not None and file_size > self._max_upload_size:
            raise ValueError(
                f"文件超过上传大小上限: {file_size} > {self._max_upload_size}（规范 §22.2）"
            )
        # 后缀白名单校验（规范 §22.2，禁止可执行/脚本文件上传）
        self._validator.validate_extension(file_name)
        if chunk_size == 0:  # 客户端明确不分片
            if file_size > self.LARGE_FILE_THRESHOLD:
                raise ValueError("大文件（>50MB）必须分片上传（规范 §22.4）")
            chunk_size = file_size
        elif chunk_size is None:
            # 小文件整体作为单分片；大文件（>50MB）自动按默认分片大小分片
            chunk_size = self._default_chunk_size if file_size > self.LARGE_FILE_THRESHOLD else file_size
        total_chunks = max(1, math.ceil(file_size / chunk_size))
        task = UploadTask(
            upload_id="",
            file_name=file_name,
            file_size=file_size,
            chunk_size=chunk_size,
            total_chunks=total_chunks,
        )
        return await self._store.create(task)

    async def upload_part(self, upload_id: str, part_number: int, data: bytes) -> None:
        """上传单个分片（规范 §22.4：逐片上传，失败重试幂等）。

        :param part_number: 分片序号（从 1 开始；首片校验内容魔数，规范 §22.2）
        :raises ValueError: 任务不存在、已合并、分片号/大小非法或首片魔数不匹配
        """
        task = await self._require_task(upload_id)
        if task.status == UploadStatus.COMPLETED:
            raise ValueError(f"上传任务已完成: {upload_id}")
        if part_number < 1 or part_number > task.total_chunks:
            raise ValueError(f"分片序号越界: {part_number}（范围 1~{task.total_chunks}）")
        if len(data) > task.chunk_size:
            raise ValueError(f"分片超过大小上限: {len(data)} > {task.chunk_size}")
        # 首片内容魔数校验（规范 §22.2：内容签名校验，防改名绕过）
        if part_number == 1:
            self._validator.validate_magic(data)
        await self._part_storage.save_part(upload_id, part_number, data)
        await self._store.mark_part_uploaded(upload_id, part_number)

    async def list_uploaded_parts(self, upload_id: str) -> list[int]:
        """列出已上传分片（断点续传：客户端据此续传缺失分片，规范 §22.4）"""
        await self._require_task(upload_id)
        return await self._store.list_uploaded_parts(upload_id)

    async def complete(self, upload_id: str, expected_md5: str | None = None) -> str:
        """合并分片完成上传（规范 §22.4：合并校验 MD5/大小，合并后清理分片与临时任务记录）。

        :param expected_md5: 客户端计算的合并文件 MD5（可选校验）
        :return: 合并完成后的对象 Key
        :raises ValueError: 分片不完整或 MD5 校验失败
        """
        task = await self._require_task(upload_id)
        if task.status == UploadStatus.COMPLETED:
            return task.object_key
        uploaded = set(await self._store.list_uploaded_parts(upload_id))
        expected = set(range(1, task.total_chunks + 1))
        if not expected.issubset(uploaded):
            missing = sorted(expected - uploaded)
            raise ValueError(f"分片不完整，缺失: {missing}")
        # MD5 校验须在合并（分片清理）前基于分片内容计算
        if expected_md5 is not None:
            actual = await self._compute_merged_md5(upload_id)
            if actual != expected_md5:
                await self._part_storage.remove_task(upload_id)
                raise ValueError(f"MD5 校验失败: 期望 {expected_md5}，实际 {actual}")
        object_key = f"uploads/{upload_id}/{task.file_name}"
        merged_size = await self._part_storage.merge(upload_id, object_key)
        if merged_size != task.file_size:
            await self._part_storage.remove_task(upload_id)
            raise ValueError(f"合并大小不一致: 期望 {task.file_size}，实际 {merged_size}")
        await self._store.complete(upload_id, object_key)
        await self._part_storage.remove_task(upload_id)
        return object_key

    async def cancel(self, upload_id: str) -> None:
        """取消上传：仅清理当前任务的分片与临时任务记录（规范 §22.4 合并后/中断清理，禁止误删其他任务）"""
        await self._require_task(upload_id)
        await self._part_storage.remove_task(upload_id)
        await self._store.remove(upload_id)

    async def cleanup_stale(self, ttl_hours: int = 24) -> int:
        """清理过期未完成任务记录与分片临时目录（规范 §22.4：临时任务记录/临时目录 TTL 清理，配合定时任务）。

        任务记录清理（_store.cleanup）与分片临时目录清理（part_storage.cleanup_expired，
        仅本地实现支持）联动，返回清理总数。
        """
        before = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
        removed = await self._store.cleanup(before)
        cleanup_expired = getattr(self._part_storage, "cleanup_expired", None)
        if cleanup_expired is not None:
            removed += await cleanup_expired(before)
        return removed

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _require_task(self, upload_id: str) -> UploadTask:
        """获取任务，不存在抛 ValueError"""
        task = await self._store.get(upload_id)
        if task is None:
            raise ValueError(f"上传任务不存在: {upload_id}")
        return task

    async def _compute_merged_md5(self, upload_id: str) -> str:
        """计算已上传分片合并后的 MD5（SHA-256 摘要由业务侧扩展；此处对齐规范 MD5 校验要求）"""
        hasher = hashlib.md5()
        parts = await self._part_storage.list_parts(upload_id)
        for n in parts:
            data = await self._part_storage.read_part(upload_id, n)
            hasher.update(data)
        return hasher.hexdigest()
