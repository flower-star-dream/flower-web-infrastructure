"""
内存任务记录存储

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 基于内存字典 + threading.Lock 的任务记录存储（默认实现，单实例场景），
              乐观锁更新：version 不匹配时拒绝写入（防并发覆盖终态）。
              线程安全：TaskExecutor 支持主事件循环与 submit_in_thread（线程池 asyncio.run）
              两条并发路径，asyncio.Lock 无法跨线程互斥，故使用 threading.Lock 统一保护；
              容量上限：max_records（默认 10000），超限按提交时间淘汰最旧记录，防内存无限增长。
"""
from __future__ import annotations

import threading

from web_infra.task.task_record import TaskRecord
from web_infra.task.task_record_store import TaskRecordStoreInterface


class InMemoryTaskRecordStore(TaskRecordStoreInterface):
    """内存任务记录存储（默认实现）

    @Stateful：进程内内存存储，单实例/单进程部署，多实例需替换为分布式实现（S1-1）。
    容量有界（max_records），超出后按提交时间淘汰最旧记录。
    """

    def __init__(self, max_records: int = 10000) -> None:
        """初始化任务记录存储。

        :param max_records: 记录条数上限（默认 10000；<=0 表示不限制），
            超出后按 submit_at 淘汰最旧记录，防止长期运行内存无限增长
        """
        self._records: dict[str, TaskRecord] = {}
        self._lock = threading.Lock()
        self._max_records = max_records

    async def save(self, record: TaskRecord) -> None:
        with self._lock:
            self._records[record.task_id] = record
            self._evict_locked()

    async def load(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._records.get(task_id)

    async def update(self, record: TaskRecord) -> bool:
        with self._lock:
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
        with self._lock:
            return list(self._records.values())

    def _evict_locked(self) -> None:
        """容量上限淘汰：超限时按提交时间淘汰最旧记录（调用方必须持有 _lock）"""
        if self._max_records <= 0 or len(self._records) <= self._max_records:
            return
        overflow = len(self._records) - self._max_records
        oldest_ids = sorted(
            self._records,
            key=lambda tid: self._records[tid].submit_at,
        )[:overflow]
        for tid in oldest_ids:
            self._records.pop(tid, None)
