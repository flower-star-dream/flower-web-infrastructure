"""
消息消费者接口

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 消息消费者抽象接口（规范 §9）。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from web_infra.capabilities.mq.message import MessageHandler


@runtime_checkable
class MessageConsumerInterface(Protocol):
    """消息消费者抽象接口"""

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        """订阅主题并注册处理器"""
        ...

    async def start(self) -> None:
        """启动消费"""
        ...

    async def stop(self) -> None:
        """停止消费"""
        ...
