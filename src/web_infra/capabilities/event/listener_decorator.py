"""
事件监听器装饰器

@Author: 花海
@Date: 2026/08/22 17:00
@Description: @event_listener 声明式注册监听器（对标 Spring @EventListener）：装饰函数即自动注册进
              EventListenerRegistry；支持 order（执行顺序）、async_mode（异步分发）。
              事务提交后触发由发布方用 EventBus.publish_after_commit(event) 实现（本装饰器不感知）。
"""
from __future__ import annotations

from typing import Any, Callable, TypeVar

from web_infra.capabilities.event.event import ApplicationEvent
from web_infra.capabilities.event.listener import EventListener
from web_infra.capabilities.event.listener_registry import EventListenerRegistry

R = TypeVar("R")


def event_listener(
    event: str | type[ApplicationEvent],
    *,
    order: int = 0,
    async_mode: bool = False,
) -> Callable[[Callable[..., R]], Callable[..., R]]:
    """声明式监听器装饰器。

    :param event: 事件名（str）或事件类型（type[ApplicationEvent]，自动推导 event_name 或作为 parent_type）
    :param order: 同事件多监听器执行顺序（升序）
    :param async_mode: 是否异步分发
    """

    def _decorator(fn: Callable[..., R]) -> Callable[..., R]:
        if isinstance(event, str):
            event_name = event
            parent_type = None
        else:
            event_name = event.resolve_event_name()
            parent_type = event
        listener = EventListener(
            event_name=event_name,
            handler=fn,
            order=order,
            async_mode=async_mode,
            parent_type=parent_type,
        )
        EventListenerRegistry.register(listener)
        return fn

    return _decorator
