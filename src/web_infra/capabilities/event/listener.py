"""
事件监听器契约

@Author: 花海
@Date: 2026/08/22 17:00
@Description: 事件监听器契约（对标 Spring ApplicationListener / @EventListener 包装）：
              提供 handle(event) 处理入口与 supports(event) 匹配决策；async_mode 标记是否异步分发。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from web_infra.capabilities.event.event import ApplicationEvent


@dataclass
class EventListener:
    """事件监听器。

    :param event_name: 监听的事件名（精确匹配）
    :param handler: 处理函数（同步/异步均可；async_mode=True 时 await 包装）
    :param order: 同事件多监听器执行顺序（升序）
    :param async_mode: 是否异步分发（True 则 handler 为 async/await 调用）
    :param parent_type: 父类事件类型（供 isinstance 匹配，如监听某基类事件）
    """

    event_name: str
    handler: Callable
    order: int = 0
    async_mode: bool = False
    parent_type: type[ApplicationEvent] | None = None

    def supports(self, event: ApplicationEvent) -> bool:
        """是否处理该事件：event_name 精确匹配或 isinstance 匹配父类。"""
        if self.event_name and event.event_name == self.event_name:
            return True
        if self.parent_type is not None and isinstance(event, self.parent_type):
            return True
        return False

    async def handle(self, event: ApplicationEvent) -> Any:
        """处理事件；async_mode=False 时同步调用（内部 await 若返回 awaitable）。"""
        result = self.handler(event)
        if self.async_mode and hasattr(result, "__await__"):
            return await result
        return result
