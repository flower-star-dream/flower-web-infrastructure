"""
内存 Outbox 存储

@Author: 花海
@Date: 2026/08/14 19:00
@Description: 基于内存字典 + asyncio.Lock 的 Outbox 存储（默认实现，单实例场景；规范 §21.3）。
              投递失败按指数退避设置 next_retry_at（S9-4），next_pending 仅取退避到期记录；
              重试超限置失败，支持死信状态与时间回写（P0-3/S9-7）。
              多实例需切换 MySQL 等共享实现（DDL 见 db/init/ddl/001-mq-init-ddl.sql）。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from web_infra.capabilities.mq.outbox.outbox_record import OutboxRecord
from web_infra.capabilities.mq.outbox.outbox_status import OutboxStatus
from web_infra.capabilities.mq.outbox.outbox_store_interface import OutboxStoreInterface


def _now() -> datetime:
    """当前 UTC 时间"""
    return datetime.now(timezone.utc)


class InMemoryOutboxStore(OutboxStoreInterface):
    """内存 Outbox 存储（默认实现）

    @Stateful：进程内内存存储，单实例/单进程部署，多实例需替换为分布式实现（S1-1）。
    仅限单事件循环访问（asyncio.Lock 不跨线程互斥），跨线程/跨循环场景请改用线程安全或分布式实现。
    """

    def __init__(self) -> None:
        self._records: dict[str, OutboxRecord] = {}
        self._lock = asyncio.Lock()

    async def append(self, record: OutboxRecord) -> OutboxRecord:
        """追加待发送消息（msg_id 缺省生成，状态强制待发送）"""
        async with self._lock:
            if not record.msg_id:
                record.msg_id = uuid.uuid4().hex
            record.status = OutboxStatus.PENDING
            record.created_at = record.created_at or _now()
            record.updated_at = record.updated_at or record.created_at
            record.next_retry_at = None  # 重新追加视为首次投递，无需退避
            self._records[record.msg_id] = record
            return record

    async def next_pending(self, limit: int = 100) -> list[OutboxRecord]:
        """取待发送消息（创建时间升序，且退避已到期：next_retry_at 为空或已到）"""
        async with self._lock:
            now = _now()
            pending = [
                record
                for record in self._records.values()
                if record.status == OutboxStatus.PENDING
                and (record.next_retry_at is None or record.next_retry_at <= now)
            ]
            pending.sort(key=lambda r: r.created_at or _now())
            return pending[:limit]

    async def mark_sent(self, msg_id: str) -> None:
        """投递成功：置为已发送"""
        async with self._lock:
            record = self._records.get(msg_id)
            if record is None:
                return
            record.status = OutboxStatus.SENT
            record.next_retry_at = None
            record.updated_at = _now()

    async def mark_failed(self, msg_id: str, max_retries: int, retry_delay_seconds: int | None = None) -> None:
        """投递失败：重试次数 +1；未超限设置退避时间 next_retry_at = now + retry_delay_seconds，
        超限置为失败超限并清除退避时间（规范 §9.6/S9-4 指数退避）"""
        async with self._lock:
            record = self._records.get(msg_id)
            if record is None:
                return
            record.retry_count += 1
            record.updated_at = _now()
            if record.retry_count >= max_retries:
                record.status = OutboxStatus.FAILED
                record.next_retry_at = None
            elif retry_delay_seconds is not None:
                record.next_retry_at = _now() + timedelta(seconds=retry_delay_seconds)

    async def mark_dlq(self, msg_id: str) -> None:
        """投递死信：状态置为死信并回写 dlq_at（P0-3/S9-7）"""
        async with self._lock:
            record = self._records.get(msg_id)
            if record is None:
                return
            record.status = OutboxStatus.DLQ
            record.next_retry_at = None
            record.dlq_at = _now()
            record.updated_at = _now()

    async def cleanup_sent(self, before: datetime) -> int:
        """清理已发送且创建时间早于 before 的记录（规范 §21.3：保留 7 天后清理）"""
        async with self._lock:
            removed = 0
            for msg_id, record in list(self._records.items()):
                created = record.created_at or _now()
                if record.status == OutboxStatus.SENT and created < before:
                    record.cleaned_at = _now()
                    self._records.pop(msg_id, None)
                    removed += 1
            return removed
