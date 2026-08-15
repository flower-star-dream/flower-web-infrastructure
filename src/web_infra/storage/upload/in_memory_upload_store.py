"""
内存分片上传任务存储

@Author: 花海
@Date: 2026/08/14 19:30
@Description: 基于内存字典 + asyncio.Lock 的分片上传任务存储（默认实现，单实例场景；规范 §22.4）。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from web_infra.storage.upload.upload_status import UploadStatus
from web_infra.storage.upload.upload_store_interface import UploadStoreInterface
from web_infra.storage.upload.upload_task import UploadTask


class InMemoryUploadStore(UploadStoreInterface):
    """内存分片上传任务存储（默认实现）

    @Stateful：进程内内存存储，单实例/单进程部署，多实例需替换为分布式实现（S1-1）。
    仅限单事件循环访问（asyncio.Lock 不跨线程互斥），跨线程/跨循环场景请改用线程安全或分布式实现。
    """

    def __init__(self) -> None:
        self._tasks: dict[str, UploadTask] = {}
        self._lock = asyncio.Lock()

    async def create(self, task: UploadTask) -> UploadTask:
        """创建任务（upload_id 缺省生成）"""
        async with self._lock:
            if not task.upload_id:
                task.upload_id = uuid.uuid4().hex
            task.created_at = task.created_at or datetime.now(timezone.utc)
            self._tasks[task.upload_id] = task
            return task

    async def get(self, upload_id: str) -> UploadTask | None:
        """查询任务"""
        async with self._lock:
            return self._tasks.get(upload_id)

    async def mark_part_uploaded(self, upload_id: str, part_number: int) -> None:
        """记录分片上传成功"""
        async with self._lock:
            task = self._tasks.get(upload_id)
            if task is not None:
                task.uploaded_parts.add(part_number)

    async def list_uploaded_parts(self, upload_id: str) -> list[int]:
        """列出已上传分片序号（升序）"""
        async with self._lock:
            task = self._tasks.get(upload_id)
            return sorted(task.uploaded_parts) if task is not None else []

    async def complete(self, upload_id: str, object_key: str) -> None:
        """标记任务合并完成"""
        async with self._lock:
            task = self._tasks.get(upload_id)
            if task is not None:
                task.status = UploadStatus.COMPLETED
                task.object_key = object_key

    async def remove(self, upload_id: str) -> None:
        """定向删除指定上传任务记录（仅当前任务，不触碰其他任务）"""
        async with self._lock:
            self._tasks.pop(upload_id, None)

    async def cleanup(self, before: datetime) -> int:
        """清理过期任务记录（返回清理条数）"""
        async with self._lock:
            removed = 0
            for upload_id, task in list(self._tasks.items()):
                created = task.created_at or datetime.now(timezone.utc)
                if created < before:
                    self._tasks.pop(upload_id, None)
                    removed += 1
            return removed
