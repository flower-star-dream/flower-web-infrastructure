"""
共享线程池与有界队列整改单元测试

@Author: 花海
@Date: 2026/08/15
@Description: 验证 S14-2 有界队列与拒绝策略 / S14-4 统一共享线程池整改：
              队列满提交抛 RejectedExecutionError、拒绝后不阻塞正常提交、
              共享池进程内单例、shutdown 后自动重建、TaskExecutor 拒绝路径集成。
"""
import threading
import time

import pytest

from web_infra.capabilities.task import InMemoryTaskRecordStore, TaskExecutor
from web_infra.capabilities.task.shared_thread_pool import (
    RejectedExecutionError,
    get_shared_thread_pool,
    shutdown_shared_pool,
)


@pytest.fixture(autouse=True)
def _fresh_shared_pool():
    """每个用例前后重置共享池，避免进程内单例状态跨用例串扰"""
    shutdown_shared_pool()
    yield
    shutdown_shared_pool()


def test_bounded_queue_rejects_when_full():
    """有界队列：提交超过上限被拒绝（RejectedExecutionError，规范 §14.2）"""
    pool = get_shared_thread_pool(max_workers=1, max_queue_size=2)
    assert pool.max_queue_size == 2  # 默认 = max_workers × 2（此处显式指定）
    started = threading.Event()
    release = threading.Event()

    def blocking() -> None:
        started.set()
        release.wait(timeout=5)

    def quick() -> None:
        time.sleep(0.05)

    pool.submit(blocking)  # 占用唯一 worker（执行中）
    assert started.wait(5)
    pool.submit(quick)  # 排队 1
    pool.submit(quick)  # 排队 2（gate 满：1 执行中 + 2 排队 = 上限 2 已占满）
    with pytest.raises(RejectedExecutionError):
        pool.submit(quick)  # 第 4 个提交：队列已满，拒绝且不阻塞调用方
    release.set()


def test_rejection_does_not_block_later_submit():
    """拒绝后不阻塞正常提交：队列腾出名额后提交成功"""
    pool = get_shared_thread_pool(max_workers=1, max_queue_size=1)
    started = threading.Event()
    release = threading.Event()

    def blocking() -> None:
        started.set()
        release.wait(timeout=5)

    def quick() -> None:
        time.sleep(0.05)

    pool.submit(blocking)
    assert started.wait(5)
    pool.submit(quick)
    with pytest.raises(RejectedExecutionError):
        pool.submit(quick)
    release.set()
    time.sleep(0.3)  # 等待 worker 完成排队的 quick，腾出名额
    done = threading.Event()
    pool.submit(done.set)  # 不抛异常、不被阻塞
    assert done.wait(5)


def test_shared_pool_singleton():
    """共享池单例：两次获取返回同一实例（规范 §14.4 统一共享线程池）"""
    first = get_shared_thread_pool()
    second = get_shared_thread_pool()
    assert first is second


def test_shared_pool_rebuild_after_shutdown():
    """shutdown 后重建：关闭后再获取得到新实例且可正常提交"""
    first = get_shared_thread_pool()
    shutdown_shared_pool()
    second = get_shared_thread_pool()
    assert first is not second
    done = threading.Event()
    second.submit(done.set)
    assert done.wait(5)


def test_task_executor_submit_in_thread_rejects_when_full():
    """TaskExecutor.submit_in_thread：队列满抛 RejectedExecutionError（拒绝路径集成）"""
    store = InMemoryTaskRecordStore()
    executor = TaskExecutor(store, max_workers=1, max_queue_size=1)
    started = threading.Event()
    release = threading.Event()

    async def blocking_job() -> None:
        started.set()
        release.wait(timeout=5)

    async def quick_job() -> None:
        return None

    executor.submit_in_thread(blocking_job)  # 占用唯一 worker（执行中）
    assert started.wait(5)
    executor.submit_in_thread(quick_job)  # 排队（gate 满：1 执行中 + 1 排队）
    with pytest.raises(RejectedExecutionError):
        executor.submit_in_thread(quick_job)  # 第 3 个提交：拒绝
    release.set()
    executor.close()
