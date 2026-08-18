"""
单供应商并发控制单元测试

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 验证并发限制、排队超时快速失败与释放（AI 规范 §5.2）。
"""
import asyncio

import pytest

from web_infra.capabilities.ai import ConcurrencyGuard
from web_infra.infra.error import BizException


@pytest.mark.asyncio
async def test_concurrency_limited():
    """并发上限生效：超过上限的获取被阻塞至超时"""
    guard = ConcurrencyGuard(max_concurrency=1, queue_capacity=0, wait_timeout_seconds=0.1)
    await guard.acquire()
    with pytest.raises(BizException):
        await guard.acquire()  # 槽被占用，超时快速失败
    guard.release()
    await guard.acquire()  # 释放后可获取
    guard.release()


@pytest.mark.asyncio
async def test_bounded_queue_rejects_overflow():
    """有界排队：排队容量满后，新请求等待超时快速失败（E1-RATE-000）"""
    guard = ConcurrencyGuard(max_concurrency=1, queue_capacity=1, wait_timeout_seconds=0.1)
    await guard.acquire()  # 占用执行槽与唯一排队位

    # 一个请求进入排队等待执行槽
    queued = asyncio.create_task(guard.acquire())
    await asyncio.sleep(0.02)

    # 排队位已满：新请求等待超时快速失败
    with pytest.raises(BizException) as exc_info:
        await guard.acquire()
    assert exc_info.value.code == "E1-RATE-000"

    # 释放执行槽；排队者与当前请求存在超时竞态，成功或超时失败均容忍
    guard.release()
    results = await asyncio.gather(queued, return_exceptions=True)
    assert all(isinstance(r, BizException) or r is None for r in results)


@pytest.mark.asyncio
async def test_context_manager():
    """异步上下文管理器正常获取/释放"""
    guard = ConcurrencyGuard(max_concurrency=1, wait_timeout_seconds=0.1)
    async with guard:
        pass  # 进入临界区


@pytest.mark.asyncio
async def test_concurrent_execution_count():
    """并发执行数不超过上限"""
    guard = ConcurrencyGuard(max_concurrency=2, wait_timeout_seconds=1.0)
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal active, peak
        async with guard:
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.05)
            async with lock:
                active -= 1

    await asyncio.gather(*(worker() for _ in range(5)))
    assert peak <= 2


@pytest.mark.asyncio
async def test_queue_slot_released_on_execution_timeout():
    """执行槽超时时已持有的排队槽名额归还：排队容量不泄漏，后续请求仍可正常获取"""
    guard = ConcurrencyGuard(max_concurrency=1, queue_capacity=1, wait_timeout_seconds=0.05)
    await guard.acquire()  # 占用唯一执行槽
    with pytest.raises(BizException):
        await guard.acquire()  # 排队后执行槽超时快速失败
    guard.release()  # 释放执行槽
    # 若排队名额泄漏（BoundedSemaphore 计数归零），此处排队槽已满会立即超时失败；
    # 名额已归还时应正常获取成功
    await guard.acquire()
    guard.release()
