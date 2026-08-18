"""
单供应商并发控制与有界排队

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 模型网关单供应商并发控制（AI 规范 §5.2）：
              执行槽（Semaphore 限制并发）+ 排队槽（BoundedSemaphore 限制排队容量）；
              等待超时快速失败，超限抛 E1-RATE-000（本地限流）。
"""
from __future__ import annotations

import asyncio
from typing import Any

from web_infra.infra.error import CommonErrorCode


class ConcurrencyGuard:
    """单供应商并发控制：执行槽 + 有界排队"""

    def __init__(self, max_concurrency: int = 8, queue_capacity: int = 16, wait_timeout_seconds: float = 1.0) -> None:
        """初始化并发控制器。

        :param max_concurrency: 单供应商最大并发执行数（对齐供应商并发配额，AI 规范 §5.2）
        :param queue_capacity: 排队容量（0 表示不限制排队人数，仅受执行槽约束）
        :param wait_timeout_seconds: 获取执行槽的最大等待时长（秒），超时快速失败
        """
        if max_concurrency <= 0:
            raise ValueError("max_concurrency 必须大于 0")
        self._execution_slots = asyncio.Semaphore(max_concurrency)
        self._queue_slots: asyncio.BoundedSemaphore | None = (
            asyncio.BoundedSemaphore(queue_capacity) if queue_capacity > 0 else None
        )
        self._wait_timeout_seconds = wait_timeout_seconds

    async def acquire(self) -> None:
        """获取执行槽（含排队限制），超时抛 E1-RATE-000（本地限流，AI 规范 §5.3）"""
        try:
            # 1. 排队槽（有界）：队列满且超时未进入则快速失败
            if self._queue_slots is not None:
                await asyncio.wait_for(self._queue_slots.acquire(), timeout=self._wait_timeout_seconds)
            # 2. 执行槽：等待并发执行位置（获取失败/取消时归还已持有的排队槽，防名额泄漏）
            try:
                await asyncio.wait_for(self._execution_slots.acquire(), timeout=self._wait_timeout_seconds)
            except BaseException:
                # 执行槽超时/被取消：排队槽名额已成功持有，必须归还后再上抛，
                # 否则 BoundedSemaphore 名额永久泄漏，排队容量耗尽后所有请求快速失败且无法自愈
                if self._queue_slots is not None:
                    self._queue_slots.release()
                raise
        except asyncio.TimeoutError:
            raise CommonErrorCode.RATE_LIMITED.to_exception(message="模型调用并发超限，请稍后重试")

    def release(self) -> None:
        """释放执行槽与排队槽"""
        self._execution_slots.release()
        if self._queue_slots is not None:
            self._queue_slots.release()

    async def __aenter__(self) -> "ConcurrencyGuard":
        """异步上下文管理器入口：获取执行槽"""
        await self.acquire()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """异步上下文管理器出口：释放执行槽"""
        self.release()
