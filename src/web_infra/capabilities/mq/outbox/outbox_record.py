"""
Outbox 消息记录

@Author: 花海
@Date: 2026/08/14 19:00
@Description: Outbox 本地事务表消息记录（规范 §21.3 附录 A.13.4 DDL 字段对齐）：
              消息 ID、业务键、消息体、状态、重试次数、创建/更新/清理时间，
              以及指数退避下次重试时间（S9-4）与死信时间（P0-3/S9-7）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from web_infra.capabilities.mq.outbox.outbox_status import OutboxStatus


@dataclass
class OutboxRecord:
    """Outbox 消息记录（对齐规范附录 A.13.4 表结构）"""

    topic: str  # 目标 Topic
    biz_id: str  # 业务键（幂等键组成之一，如 orderId，规范 §9.2）
    payload: dict[str, Any] = field(default_factory=dict)  # 消息体
    tag: str = ""  # Tag（对齐 §5.8 消息常量规范）
    msg_id: str = ""  # 消息幂等键组成之一（规范 §9.2，缺省由存储生成）
    status: OutboxStatus = OutboxStatus.PENDING  # 0 待发送 / 1 已发送 / 2 失败超限 / 3 死信
    retry_count: int = 0  # 投递重试次数（规范 §9.6）
    created_at: datetime | None = None  # 创建时间（清理判断依据，规范 §21.3）
    updated_at: datetime | None = None  # 最近一次投递/重试时间
    cleaned_at: datetime | None = None  # 清理时间（完成后回写，规范 §21.3）
    next_retry_at: datetime | None = None  # 下次可重试时间（指数退避，None 表示立即重试，S9-4）
    dlq_at: datetime | None = None  # 死信时间（进入 DLQ 时回写，P0-3/S9-7）
