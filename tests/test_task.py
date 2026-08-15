"""
异步任务调度框架单元测试

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 验证任务状态流转、心跳、死任务扫描、乐观锁终态保护与线程池回退（规范 §9/§23）。
"""
import asyncio
import time

import pytest

from web_infra.task import (
    TaskExecutor,
    TaskRecord,
    TaskStatus,
    InMemoryTaskRecordStore,
)


async def _success_job(flag: list | None = None) -> None:
    """成功任务"""
    if flag is not None:
        flag.append(True)


async def _fail_job() -> None:
    """失败任务"""
    raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_submit_success_task():
    """成功任务流转到 SUCCESS，含耗时"""
    store = InMemoryTaskRecordStore()
    executor = TaskExecutor(store)
    flag: list = []
    record = await executor.submit(lambda: _success_job(flag), task_id="t1")
    assert record.status is TaskStatus.PENDING
    # 等待任务完成（轮询）
    for _ in range(50):
        current = await store.load("t1")
        if current and current.status.is_terminal:
            break
        await asyncio.sleep(0.01)
    current = await store.load("t1")
    assert current is not None
    assert current.status is TaskStatus.SUCCESS
    assert current.duration_seconds is not None
    assert flag == [True]
    executor.close()


@pytest.mark.asyncio
async def test_submit_failed_task():
    """失败任务流转到 FAILED 并记录错误"""
    store = InMemoryTaskRecordStore()
    executor = TaskExecutor(store)
    record = await executor.submit(_fail_job, task_id="t2")
    assert record.task_id == "t2"
    for _ in range(50):
        current = await store.load("t2")
        if current and current.status.is_terminal:
            break
        await asyncio.sleep(0.01)
    current = await store.load("t2")
    assert current is not None
    assert current.status is TaskStatus.FAILED
    assert "boom" in current.error
    executor.close()


@pytest.mark.asyncio
async def test_heartbeat_refresh():
    """心跳刷新成功（RUNNING 状态），非 RUNNING 状态心跳失败"""
    store = InMemoryTaskRecordStore()
    executor = TaskExecutor(store)
    started = asyncio.Event()
    release = asyncio.Event()

    async def long_job() -> None:
        started.set()
        await release.wait()

    record = await executor.submit(lambda: long_job(), task_id="t3")
    await started.wait()
    # RUNNING 状态心跳成功
    assert await executor.heartbeat("t3") is True
    # 释放任务
    release.set()
    for _ in range(50):
        current = await store.load("t3")
        if current and current.status.is_terminal:
            break
        await asyncio.sleep(0.01)
    # 终态心跳失败
    assert await executor.heartbeat("t3") is False
    executor.close()


@pytest.mark.asyncio
async def test_scan_dead_tasks():
    """心跳超时任务被判定 DEAD"""
    store = InMemoryTaskRecordStore()
    executor = TaskExecutor(store, dead_threshold_seconds=5)
    started = asyncio.Event()
    release = asyncio.Event()

    async def stuck_job() -> None:
        started.set()
        await release.wait()

    await executor.submit(lambda: stuck_job(), task_id="t4")
    await started.wait()
    # 手动老化心跳时间（模拟任务卡死超过阈值）
    current = await store.load("t4")
    assert current is not None
    current.heartbeat_at = time.time() - 100
    await store.update(current)
    dead = await executor.scan_dead_tasks()
    assert [r.task_id for r in dead] == ["t4"]
    current = await store.load("t4")
    assert current is not None
    assert current.status is TaskStatus.DEAD
    assert "heartbeat" in current.error
    release.set()
    executor.close()


@pytest.mark.asyncio
async def test_terminal_state_protected():
    """终态保护：终态不可被并发覆盖（乐观锁版本校验）"""
    store = InMemoryTaskRecordStore()
    executor = TaskExecutor(store)
    await executor.submit(_success_job, task_id="t5")
    for _ in range(50):
        current = await store.load("t5")
        if current and current.status.is_terminal:
            break
        await asyncio.sleep(0.01)
    current = await store.load("t5")
    assert current is not None and current.status is TaskStatus.SUCCESS
    # 用旧版本强行改回 RUNNING：应被乐观锁拒绝
    stale = current.model_copy(update={"status": TaskStatus.RUNNING})
    assert await store.update(stale) is False
    after = await store.load("t5")
    assert after is not None
    assert after.status is TaskStatus.SUCCESS
    executor.close()


def test_submit_in_thread():
    """线程池回退：同步上下文提交任务并执行完成"""
    import time as _time

    store = InMemoryTaskRecordStore()
    executor = TaskExecutor(store, max_workers=2)
    flag: list = []

    async def thread_job() -> None:
        flag.append(True)

    record = executor.submit_in_thread(lambda: thread_job(), task_id="t6")
    assert record.task_id == "t6"
    # 等待线程池执行完成
    for _ in range(100):
        if flag:
            break
        _time.sleep(0.01)
    assert flag == [True]
    executor.close()


@pytest.mark.asyncio
async def test_task_record_duration():
    """任务记录耗时字段"""
    record = TaskRecord()
    assert record.duration_seconds is None
    record.start_at = time.time()
    await asyncio.sleep(0.01)
    record.end_at = time.time()
    assert record.duration_seconds is not None
    # 断言放宽为 >0：Windows 时间精度与调度抖动下，真实耗时可能不足 0.01s（仅需验证"有耗时"语义）
    assert record.duration_seconds > 0


def test_task_status_skipped_is_terminal():
    """SKIPPED 为终态（调度跳过记录不可再流转，整改 S23-1/S23-2）"""
    assert TaskStatus.SKIPPED.is_terminal is True
