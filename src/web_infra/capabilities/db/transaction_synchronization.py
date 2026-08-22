"""
事务同步回调

@Author: 花海
@Date: 2026/08/22 17:00
@Description: 事务同步回调（对标 Spring TransactionSynchronization 的 afterCommit）：注册"事务提交成功后"
              执行的回调。由 SessionScopeMixin._finalize_commit 在 commit 成功后触发（而非之前），
              保证事件在事务真正提交后才发布（避免"通知发了但事务回滚"）。
              提供 async / sync 两版触发入口，共享同一回调栈（ContextVar），供异步数据源（MySQL）与
              同步数据源（SQLite 参考实现）复用；回调异常隔离，不阻断主链路。
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Callable

logger = logging.getLogger(__name__)

#: after_commit 回调栈（ContextVar；每次事务提交后清空，防跨事务累积触发）
_CALLBACKS: ContextVar[tuple[Callable, ...]] = ContextVar("web_infra_after_commit_callbacks", default=())


def register_callback(callback: Callable) -> None:
    """注册事务提交后回调。

    :param callback: 无参回调（同步或 async 均可，返回 awaitable 时由触发方 await）
    """
    _CALLBACKS.set(_CALLBACKS.get() + (callback,))


def register_listener(publisher: Callable) -> None:
    """注册事务提交后发布回调：事务提交成功后执行（由 EventBus.publish_after_commit 构建并调用）。

    :param publisher: 无参回调（返回 awaitable 时由触发方 await）。语义："事务提交成功后，
        执行该回调以发布对应事件"。此回调不含事件对象本身，事件由调用方在闭包中捕获。
    """
    register_callback(publisher)


async def trigger_after_commit() -> None:
    """触发全部 after_commit 回调（commit 成功后），随后清空（防跨事务累积）。

    回调为 awaitable 时 await；回调异常不阻断（记录 warning 日志）。
    """
    await _run_callbacks(_drain_callbacks())


def trigger_after_commit_sync() -> None:
    """同步触发 after_commit 回调（提交成功后，SQLite 同步参考实现用）。

    与 `trigger_after_commit` 共享同一回调栈；对返回 awaitable 的回调跳过并告警
    （同步上下文不强跑 asyncio，避免在非事件循环环境报错）。
    """
    callbacks = _drain_callbacks()
    for cb in callbacks:
        try:
            result = cb()
            if hasattr(result, "__await__"):
                # 同步上下文遇到 awaitable 回调：跳过并告警（业务应避免在 SQLite 事务事件中用 async 监听器）
                logger.warning("after_commit_sync_skip_awaitable err=callback returned awaitable in sync context")
        except Exception as exc:  # noqa: BLE001 - 回调异常隔离
            logger.warning("after_commit_callback_error err=%s", exc)


def _drain_callbacks() -> list[Callable]:
    """取出并清空回调栈（上下文安全）。"""
    callbacks = _CALLBACKS.get()
    _CALLBACKS.set(())
    return list(callbacks)


async def _run_callbacks(callbacks: list[Callable]) -> None:
    """异步执行回调列表（异常隔离）。"""
    for cb in callbacks:
        try:
            result = cb()
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:  # noqa: BLE001 - 回调异常隔离
            logger.warning("after_commit_callback_error err=%s", exc)
