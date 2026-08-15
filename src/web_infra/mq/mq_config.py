"""
消息队列配置

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 消息队列配置（规范 §9 / 附录 A.13）。
              实际被 Outbox 发布器/重试消费封装使用：max_retry 重试上限、
              retry_backoff_seconds 指数退避基数（S9-4）、dead_letter_topic 死信主题（P0-3/S9-7）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class MqConfig(BaseModel):
    """消息队列配置（规范 §9 / 附录 A.13）"""

    max_retry: int = Field(default=3, description="消费/投递失败最大重试次数（规范 §9.6）")
    retry_backoff_seconds: int = Field(default=30, description="重试退避基数（秒），指数退避 base * 2^retry_count（S9-4）")
    dead_letter_topic: str = Field(default="web-dlq-topic", description="死信队列 Topic（P0-3/S9-7）")
