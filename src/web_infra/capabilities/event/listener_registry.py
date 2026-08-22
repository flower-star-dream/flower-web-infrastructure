"""
事件监听器注册表

@Author: 花海
@Date: 2026/08/22 17:00
@Description: 事件监听器注册表（类级注册，全局装配）：按事件名登记监听器，order 升序执行；
              供 EventBus 分发时解析匹配监听器。与其它注册表一致（类级 + Lock）。
"""
from __future__ import annotations

from threading import Lock
from typing import Callable, ClassVar

from web_infra.capabilities.event.event import ApplicationEvent
from web_infra.capabilities.event.listener import EventListener


class EventListenerRegistry:
    """事件监听器注册表（类级注册，全局装配；类级锁保护并发 register）"""

    _listeners: ClassVar[dict[str, list[EventListener]]] = {}
    _lock = Lock()

    @classmethod
    def register(cls, listener: EventListener) -> None:
        """登记监听器（按 event_name 聚合；重复注册覆盖同名 handler）。"""
        with cls._lock:
            bucket = cls._listeners.setdefault(listener.event_name, [])
            for i, existing in enumerate(bucket):
                if existing.handler is listener.handler:
                    bucket[i] = listener
                    return
            bucket.append(listener)
            bucket.sort(key=lambda l: l.order)

    @classmethod
    def match(cls, event: ApplicationEvent) -> list[EventListener]:
        """返回匹配该事件的监听器（event_name 精确 + 父类 isinstance），按 order 升序。"""
        with cls._lock:
            matched: list[EventListener] = []
            event_name = event.event_name
            for name, listeners in cls._listeners.items():
                if name == event_name or any(l.parent_type and isinstance(event, l.parent_type) for l in listeners):
                    matched.extend(l for l in listeners if l.supports(event))
            # 跨 bucket 归并后仍需按 order 排序（精确匹配优先父类）
            matched.sort(key=lambda l: l.order)
            return matched

    @classmethod
    def clear(cls) -> None:
        """清空全部监听器（测试/生命周期清理用）。"""
        with cls._lock:
            cls._listeners.clear()

    @classmethod
    def unregister(cls, event_name: str, handler: Callable) -> None:
        """注销指定监听器（不存在时静默）。"""
        with cls._lock:
            bucket = cls._listeners.get(event_name)
            if not bucket:
                return
            cls._listeners[event_name] = [l for l in bucket if l.handler is not handler]


def _clear() -> None:
    """清空注册表（测试专用）。"""
    EventListenerRegistry.clear()
