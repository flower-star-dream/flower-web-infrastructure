"""
统一消息结构

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一消息结构（规范 §4.5.4：消息体必须包含 code 字段）与消息处理器类型别名。
"""
from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field


def generate_message_id() -> str:
    """生成消息唯一标识（用于幂等，规范 §9.2）"""
    return uuid.uuid4().hex


class Message(BaseModel):
    """统一消息结构（规范 §4.5.4：消息体必须包含 code 字段）"""

    message_id: str = Field(default_factory=generate_message_id, description="消息唯一标识")
    topic: str = Field(description="消息 Topic")
    tag: str = Field(default="", description="消息 Tag（与业务域对齐）")
    code: str = Field(default="S0000", description="错误码（异步链路传递）")
    body: dict[str, Any] = Field(default_factory=dict, description="消息体")
    trace_id: str = Field(default="", description="链路追踪标识")
    partition_key: str | None = Field(
        default=None,
        description="业务分区键（按此哈希选分区，规范 §9.2 分区内串行；不传则无分区要求）",
    )


# 消息处理器类型
MessageHandler = Callable[[Message], Awaitable[None]]
