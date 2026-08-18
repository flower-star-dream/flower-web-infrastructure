"""
消息发布者接口

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 消息发布者抽象接口（规范 §9）。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from web_infra.capabilities.mq.message import Message


@runtime_checkable
class MessagePublisherInterface(Protocol):
    """消息发布者抽象接口"""

    async def publish(self, message: Message) -> str:
        """发送消息，返回消息 ID

        分区语义（规范 §9.2 分区内串行）：Message.partition_key 为业务分区键，
        发布端按业务主键稳定哈希选分区，同一业务主键的消息恒落入同一分区，
        在分区内按序串行消费，保证同一业务对象的消息顺序性。
        """
        ...

    async def send_delay(self, message: Message, delay_seconds: int) -> str:
        """发送延迟消息（规范 §9.5），返回消息 ID"""
        ...
