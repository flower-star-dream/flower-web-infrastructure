"""
定时任务调度器单元测试

@Author: 花海
@Date: 2026/08/14 18:00
@Description: 验证任务注册/间隔触发/超时中断/连续失败暂停/分布式锁防重复/手动触发/
              执行记录持久化（S23-1）/锁竞争超时跳过（S23-2）（规范 §23）。
"""
import asyncio

import pytest

from web_infra.capabilities.schedule import ScheduledTask, TaskScheduler
from web_infra.capabilities.task import InMemoryTaskRecordStore, TaskStatus


async def _noop() -> None:
    """空任务"""


def test_register_validates_required_fields():
    """注册校验：name/module/间隔必填"""
    scheduler = TaskScheduler()
    with pytest.raises(ValueError):
        scheduler.register(ScheduledTask(name="", module="m", interval_seconds=1, handler=_noop))
    with pytest.raises(ValueError):
        scheduler.register(ScheduledTask(name="t", module="", interval_seconds=1, handler=_noop))
    with pytest.raises(ValueError):
        scheduler.register(ScheduledTask(name="t", module="m", interval_seconds=0, handler=_noop))


@pytest.mark.asyncio
async def test_run_once_executes_handler():
    """手动触发：handler 被执行"""
    calls: list[str] = []

    async def handler() -> None:
        calls.append("done")

    scheduler = TaskScheduler()
    scheduler.register_task(name="job:demo", module="demo", interval_seconds=60, handler=handler)
    assert await scheduler.run_once("job:demo") is True
    assert calls == ["done"]


@pytest.mark.asyncio
async def test_run_once_unknown_task_raises():
    """未注册任务抛 KeyError"""
    scheduler = TaskScheduler()
    with pytest.raises(KeyError):
        await scheduler.run_once("ghost")


@pytest.mark.asyncio
async def test_timeout_interrupts_task():
    """执行超时中断（规范 §23.3），不产生无限阻塞"""
    async def slow_handler() -> None:
        await asyncio.sleep(10)

    scheduler = TaskScheduler()
    scheduler.register_task(
        name="job:slow", module="demo", interval_seconds=60, handler=slow_handler, timeout_seconds=0.05
    )
    assert await scheduler.run_once("job:slow") is False


@pytest.mark.asyncio
async def test_consecutive_failure_auto_pauses():
    """连续失败达阈值自动暂停（规范 §23.4）"""
    async def failing() -> None:
        raise RuntimeError("boom")

    scheduler = TaskScheduler()
    scheduler.register_task(
        name="job:fail", module="demo", interval_seconds=60, handler=failing, consecutive_failure_limit=2
    )
    assert await scheduler.run_once("job:fail") is False
    assert await scheduler.run_once("job:fail") is False
    assert scheduler.is_paused("job:fail")
    # 暂停后不再执行（直接跳过）
    assert await scheduler.run_once("job:fail") is False
    scheduler.resume("job:fail")
    assert not scheduler.is_paused("job:fail")


@pytest.mark.asyncio
async def test_distributed_lock_prevents_duplicate_execution():
    """分布式锁：抢锁失败则跳过本轮（多实例单实例执行，规范 §23.2）"""
    executed: list[str] = []

    async def handler() -> None:
        executed.append("x")

    class _FakeLock:
        """模拟抢锁失败：进入上下文即抛 TimeoutError（未获取锁）"""

        async def __aenter__(self) -> "_FakeLock":
            raise TimeoutError("lock busy")

        async def __aexit__(self, *args: object) -> None:
            return None

    scheduler = TaskScheduler(lock_factory=lambda name: _FakeLock())
    scheduler.register_task(name="job:locked", module="demo", interval_seconds=60, handler=handler)
    assert await scheduler.run_once("job:locked") is False
    assert executed == []  # 未抢到锁，跳过执行


@pytest.mark.asyncio
async def test_schedule_loop_runs_due_tasks():
    """调度循环：间隔到期后自动执行"""
    calls: list[str] = []

    async def handler() -> None:
        calls.append("x")

    scheduler = TaskScheduler(tick_seconds=0.01)
    scheduler.register_task(name="job:tick", module="demo", interval_seconds=0.05, handler=handler)
    scheduler.start()
    try:
        await asyncio.sleep(0.16)
    finally:
        await scheduler.stop()
    assert len(calls) >= 2  # 约 3 个周期


# ------------------------------------------------------------------
# 整改 S23-1：执行记录持久化
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_store_records_success_and_failure():
    """注入 record_store 后：成功/失败均写入独立执行记录（任务名/模块/耗时/失败原因）"""
    store = InMemoryTaskRecordStore()
    scheduler = TaskScheduler(record_store=store)

    async def ok_handler() -> None:
        return None

    async def fail_handler() -> None:
        raise RuntimeError("boom")

    scheduler.register_task(name="job:ok", module="demo", interval_seconds=60, handler=ok_handler)
    assert await scheduler.run_once("job:ok") is True
    ok_records = [r for r in await store.list_all() if r.payload.get("task_name") == "job:ok"]
    assert len(ok_records) == 1
    assert ok_records[0].status is TaskStatus.SUCCESS
    assert ok_records[0].payload["module"] == "demo"
    assert ok_records[0].duration_seconds is not None

    scheduler.register_task(name="job:fail", module="demo", interval_seconds=60, handler=fail_handler)
    assert await scheduler.run_once("job:fail") is False
    fail_records = [r for r in await store.list_all() if r.payload.get("task_name") == "job:fail"]
    assert len(fail_records) == 1
    assert fail_records[0].status is TaskStatus.FAILED
    assert "boom" in fail_records[0].error


@pytest.mark.asyncio
async def test_record_store_records_skipped_when_paused():
    """暂停后跳过：写入 SKIPPED 记录而非失败记录"""
    store = InMemoryTaskRecordStore()

    async def failing() -> None:
        raise RuntimeError("boom")

    scheduler = TaskScheduler(record_store=store)
    scheduler.register_task(
        name="job:pause", module="demo", interval_seconds=60, handler=failing, consecutive_failure_limit=1
    )
    assert await scheduler.run_once("job:pause") is False
    assert scheduler.is_paused("job:pause")
    assert await scheduler.run_once("job:pause") is False  # 暂停后直接跳过

    records = await store.list_all()
    status_counts: dict[TaskStatus, int] = {}
    for record in records:
        status_counts[record.status] = status_counts.get(record.status, 0) + 1
    assert status_counts[TaskStatus.FAILED] == 1
    assert status_counts[TaskStatus.SKIPPED] == 1


@pytest.mark.asyncio
async def test_record_store_none_by_default_no_records():
    """未注入 record_store（默认）：不产生执行记录（向后兼容）"""
    scheduler = TaskScheduler()

    async def handler() -> None:
        return None

    scheduler.register_task(name="job:plain", module="demo", interval_seconds=60, handler=handler)
    assert await scheduler.run_once("job:plain") is True  # 不抛异常、正常执行


# ------------------------------------------------------------------
# 整改 S23-2：锁竞争超时记为跳过而非失败
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lock_timeout_skips_without_failure_count():
    """锁被占用（TimeoutError）：跳过本轮，不累计连续失败、不触发误暂停、写入 SKIPPED 记录"""
    executed: list[str] = []
    store = InMemoryTaskRecordStore()

    async def handler() -> None:
        executed.append("x")

    class _BusyLock:
        """模拟抢锁失败：进入上下文即抛 TimeoutError（未获取锁）"""

        async def __aenter__(self) -> "_BusyLock":
            raise TimeoutError("lock busy")

        async def __aexit__(self, *args: object) -> None:
            return None

    scheduler = TaskScheduler(lock_factory=lambda name: _BusyLock(), record_store=store)
    # limit=1：若锁超时被误计为失败，第一次就会暂停
    scheduler.register_task(
        name="job:lockbusy", module="demo", interval_seconds=60, handler=handler, consecutive_failure_limit=1
    )
    assert await scheduler.run_once("job:lockbusy") is False
    assert await scheduler.run_once("job:lockbusy") is False
    assert executed == []
    assert not scheduler.is_paused("job:lockbusy")

    records = await store.list_all()
    assert len(records) == 2
    assert all(r.status is TaskStatus.SKIPPED for r in records)
    assert all("lock" in r.error for r in records)


@pytest.mark.asyncio
async def test_lock_timeout_does_not_reset_failure_count():
    """锁超时跳过不累计失败：跳过后的真实失败从 0 开始计数，不受跳过影响"""
    calls: list[str] = []
    store = InMemoryTaskRecordStore()

    class _FlakyLock:
        """第一次进入抛 TimeoutError（锁竞争），后续放行（跨调用共享实例）"""

        def __init__(self) -> None:
            self._fail_first = True

        async def __aenter__(self) -> "_FlakyLock":
            if self._fail_first:
                self._fail_first = False
                raise TimeoutError("lock busy")
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    async def failing() -> None:
        raise RuntimeError("boom")

    flaky_lock = _FlakyLock()
    scheduler = TaskScheduler(lock_factory=lambda name: flaky_lock, record_store=store)
    scheduler.register_task(
        name="job:flaky", module="demo", interval_seconds=60, handler=failing, consecutive_failure_limit=2
    )
    # 第 1 次：锁超时跳过（不计失败）；第 2 次：抢到锁但执行失败（第 1 次真实失败）
    assert await scheduler.run_once("job:flaky") is False
    assert await scheduler.run_once("job:flaky") is False
    # 若跳过被误计为失败，第 2 次将达到 limit=2 触发暂停
    assert not scheduler.is_paused("job:flaky")
    assert calls == []
