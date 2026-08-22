"""
进程内事件总线

@Author: 花海
@Date: 2026/08/22 17:00
@Description: 进程内事件总线（对标 Spring ApplicationEvent / @EventListener）：服务内解耦，
              区别于 MQ（跨服务）。提供 ApplicationEvent、@event_listener、EventBus；
              支持同步/异步分发、异常隔离、order 排序与事务事件（AFTER_COMMIT）。
"""
from web_infra.capabilities.event.event import ApplicationEvent
from web_infra.capabilities.event.listener import EventListener
from web_infra.capabilities.event.listener_registry import EventListenerRegistry
from web_infra.capabilities.event.listener_decorator import event_listener
from web_infra.capabilities.event.publisher import EventPublisher
from web_infra.capabilities.event.event_bus import EventBus
from web_infra.capabilities.event.event_error import EventErrorCode

__all__ = [
    "ApplicationEvent",
    "EventListener",
    "EventListenerRegistry",
    "event_listener",
    "EventPublisher",
    "EventBus",
    "EventErrorCode",
]
