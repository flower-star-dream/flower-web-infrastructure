"""
事件发布器

@Author: 花海
@Date: 2026/08/22 17:00
@Description: EventPublisher 发布事件：从 EventListenerRegistry 解析匹配监听器，按 order 分发；
              异常隔离（fail_fast）。监听器是否异步由 EventListener.async_mode 决定。
              由 EventBus 组合使用。
"""
from __future__ import annotations

import logging
from typing import Any

from web_infra.capabilities.event.event import ApplicationEvent
from web_infra.capabilities.event.listener_registry import EventListenerRegistry

logger = logging.getLogger(__name__)


class EventPublisher:
    """事件发布器（对标 Spring ApplicationEventPublisher）。"""

    def __init__(self, *, fail_fast: bool = False) -> None:
        """初始化发布器。

        :param fail_fast: 单监听器异常是否阻断其余（True 抛错；False 记录日志继续）。
            监听器是否异步由 `EventListener.async_mode` 决定（发布器不感知）。
        """
        self._fail_fast = fail_fast

    async def publish(self, event: ApplicationEvent) -> None:
        """发布事件：按 order 分发匹配监听器。

        :raises Exception: fail_fast=True 时监听器异常向上抛（默认 False 记录日志不阻断）
        """
        for listener in EventListenerRegistry.match(event):
            try:
                result = await listener.handle(event)
            except Exception as exc:  # noqa: BLE001 - 监听器异常隔离
                if self._fail_fast:
                    raise
                logger.warning("event_listener_error event=%s handler=%s err=%s", event.event_name, listener.event_name, exc)
