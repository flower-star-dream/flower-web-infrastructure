"""
内存任务记录存储

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 基于内存字典 + asyncio.Lock 的任务记录存储（默认实现，单实例场景），
              乐观锁更新：version 不匹配时拒绝写入（防并发覆盖终态）。
"""
from __future__ import annotations

import asyncio

from web_infra.task.task_record import TaskRecord
from web_infra.task.task_record_store import TaskRecordStoreInterface


class InMemoryTaskRecordStore(TaskRecordStoreInterface):
    """内存任务记录存储（默认实现）

    @Stateful：进程内内存存储，单实例/单进程部署，多实例需替换为分布式实现（S1-1）。
    """

    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}
        self._lock = asyncio.Lock()

    async def save(self, record: TaskRecord) -> None:
        async with self._lock:
            self._records[record.task_id] = record

    async def load(self, task_id: str) -> TaskRecord | None:
        async with self._lock:
            return self._records.get(task_id)

    async def update(self, record: TaskRecord) -> bool:
        async with self._lock:
            current = self._records.get(record.task_id)
            if current is None or current.version != record.version:
                return False
            # 终态保护：当前终态不允许回退到非终态（防并发/旧快照覆盖）
            if current.status.is_terminal and not record.status.is_terminal:
                return False
            updated = record.model_copy(update={"version": record.version + 1})
            self._records[record.task_id] = updated
            # 写回调用方版本，支持同一 record 连续更新
            record.version = updated.version
            return True

    async def list_all(self) -> list[TaskRecord]:
        async with self._lock:
            return list(self._records.values())
