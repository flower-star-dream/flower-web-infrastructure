"""
事件总线

@Author: 花海
@Date: 2026/08/22 17:00
@Description: EventBus 统一入口：组合 EventPublisher，提供 publish 与 publish_after_commit（事务提交后
              事件）两个发布方法。装配到 app.state.event；默认 app.event.fail_fast=false。
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
