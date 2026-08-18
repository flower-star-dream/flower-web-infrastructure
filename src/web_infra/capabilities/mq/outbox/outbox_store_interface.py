"""
Outbox 存储接口

@Author: 花海
@Date: 2026/08/14 19:00
@Description: Outbox 本地事务表存储抽象接口（规范 §21.3：定时扫描待发送 -> 投递 -> 更新状态；
              投递失败按指数退避设置 next_retry_at（S9-4），重试超限置失败并投递死信（P0-3/S9-7）；
              已发送记录保留 7 天后清理）。内存实现默认，MySQL 等实现接入 DDL 附录 A.13.4。
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from web_infra.capabilities.mq.outbox.outbox_record import OutboxRecord


@runtime_checkable
class OutboxStoreInterface(Protocol):
    """Outbox 存储抽象接口"""

    async def append(self, record: OutboxRecord) -> OutboxRecord:
        """追加一条待发送消息（本地事务提交时调用），返回补齐 msg_id/created_at 的记录"""
        ...

    async def next_pending(self, limit: int = 100) -> list[OutboxRecord]:
        """取待发送消息（按创建时间升序，且仅取退避已到期 next_retry_at <= now 的记录，
        供轮询投递，规范 §21.3/S9-4）"""
        ...

    async def mark_sent(self, msg_id: str) -> None:
        """投递成功：状态置为已发送（规范 §21.3 投递成功后更新状态）"""
        ...

    async def mark_failed(self, msg_id: str, max_retries: int, retry_delay_seconds: int | None = None) -> None:
        """投递失败：重试次数 +1；未超限时设置 next_retry_at = now + retry_delay_seconds（指数退避，
        超限置为失败超限并清除退避时间；规范 §9.6/S9-4）"""
        ...

    async def mark_dlq(self, msg_id: str) -> None:
        """投递死信：状态置为死信并回写 dlq_at（发布器已投递死信主题后调用，P0-3/S9-7）"""
        ...

    async def cleanup_sent(self, before: datetime) -> int:
        """清理已发送超过保留期的记录（以 created_at 判断，规范 §21.3），返回清理条数"""
        ...
