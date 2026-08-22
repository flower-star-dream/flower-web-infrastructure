"""
事件总线

@Author: 花海
@Date: 2026/08/22 17:00
@Description: EventBus 统一入口：组合 EventPublisher，提供 publish 与 publish_after_commit（事务提交后
              事件）两个发布方法。装配到 app.state.event；默认 app.event.fail_fast=false。
              另提供模块级总线持有器（_current_event_bus）与发布入口 publish_event：
              供无 app 引用的框架组件（如 JWTUtil、SocialLoginService 类级/普通组件）发布事件。
"""
from __future__ import annotations

from typing import Any

from web_infra.capabilities.event.event import ApplicationEvent
from web_infra.capabilities.event.publisher import EventPublisher


class EventBus:
    """事件总线（统一发布入口。对标 Spring ApplicationEventPublisher）。"""

    def __init__(self, *, fail_fast: bool = False) -> None:
        self._publisher = EventPublisher(fail_fast=fail_fast)

    async def publish(self, event: ApplicationEvent) -> None:
        """发布事件（同步/异步监听器统一分发；发布即触发）。

        :param event: 事件对象
        """
        await self._publisher.publish(event)

    async def publish_after_commit(self, event: ApplicationEvent) -> None:
        """发布事务提交后事件（对标 Spring @TransactionalEventListener(AFTER_COMMIT)）。

        仅在事务内调用：把"发布该事件"注册为 after_commit 回调（`transaction_synchronization`），
        当事务提交成功后由 `_finalize_commit` 触发；事务回滚则不触发（事件不发布）。
        若不在事务内调用，回调缺省在最近一次提交后触发（无外层事务时等价于立即注册到下次提交）。

        :param event: 事件对象
        :raises RuntimeError: 未在事务同步上下文中（无任何 after_commit 注册入口）——落地时按需
        """
        from web_infra.capabilities.db.transaction_synchronization import register_listener

        async def _cb() -> None:
            await self._publisher.publish(event)

        register_listener(_cb)


# ------------------------------------------------------------------
# 模块级总线持有器：供无 app 引用的框架组件发布事件（事件总线核心化）
# ------------------------------------------------------------------
_current_event_bus: EventBus | None = None


def set_current_event_bus(bus: EventBus | None) -> None:
    """设置模块级事件总线持有器（供无 app 引用的框架组件发布事件）。

    :param bus: 当前事件总线（None 表示不装配，发布侧 no-op）
    """
    global _current_event_bus
    _current_event_bus = bus


def get_current_event_bus() -> EventBus | None:
    """获取模块级事件总线持有器（未设置返回 None，发布侧 no-op）。"""
    return _current_event_bus


def clear_current_event_bus() -> None:
    """清空模块级事件总线持有器（应用停机后调用，避免悬挂引用残留）。"""
    global _current_event_bus
    _current_event_bus = None


async def publish_event(event: ApplicationEvent) -> None:
    """发布事件（无 app 引用的框架组件发布入口）：总线为 None 时 no-op，否则转发到总线。

    :param event: 事件对象
    """
    bus = _current_event_bus
    if bus is not None:
        await bus.publish(event)
