"""
调度失败退避整改单元测试

@Author: 花海
@Date: 2026/08/15
@Description: 验证 S23-3 失败退避整改：连续失败后 next_interval 指数递增、成功清零、
              退避封顶、失败次数按任务名隔离、自动轮询按退避延后触发（规范 §23.3）。
"""
import pytest

from web_infra.schedule import TaskScheduler


@pytest.mark.asyncio
async def test_backoff_grows_and_resets_on_success():
    """连续失败后退避递增；成功执行清零回到原间隔"""
    async def failing() -> None:
        raise RuntimeError("boom")

    scheduler = TaskScheduler(retry_backoff_base_seconds=10.0, max_retry_backoff_seconds=3600.0)
    scheduler.register_task(
        name="job:bf", module="demo", interval_seconds=60, handler=failing, consecutive_failure_limit=100
    )
    assert await scheduler.run_once("job:bf") is False  # 第 1 次失败
    first = scheduler.next_interval("job:bf", 60.0)
    assert first == 60.0 + 10.0 * 2  # 2^1 指数退避
    assert await scheduler.run_once("job:bf") is False  # 第 2 次失败
    second = scheduler.next_interval("job:bf", 60.0)
    assert second == 60.0 + 10.0 * 4  # 2^2 指数退避
    assert second > first

    # 成功执行清零
    async def ok() -> None:
        return None

    scheduler.register_task(name="job:bf", module="demo", interval_seconds=60, handler=ok)
    assert await scheduler.run_once("job:bf") is True
    assert scheduler.next_interval("job:bf", 60.0) == 60.0


def test_backoff_capped_at_max():
    """退避封顶：min(基数 × 2^n, 上限)"""
    scheduler = TaskScheduler(retry_backoff_base_seconds=10.0, max_retry_backoff_seconds=100.0)
    scheduler._consecutive_failures["job:cap"] = 10
    assert scheduler.next_interval("job:cap", 60.0) == 160.0  # 60 + 100（封顶）


def test_backoff_isolated_per_task_name():
    """失败次数按任务名隔离"""
    scheduler = TaskScheduler(retry_backoff_base_seconds=10.0, max_retry_backoff_seconds=3600.0)
    scheduler._consecutive_failures["job:a"] = 3
    assert scheduler.next_interval("job:a", 60.0) == 60.0 + 10.0 * 8
    assert scheduler.next_interval("job:b", 60.0) == 60.0  # 未失败任务无退避


def test_next_interval_without_failures_returns_base():
    """无失败记录（含未注册任务）：返回原间隔"""
    scheduler = TaskScheduler()
    assert scheduler.next_interval("job:new", 30.0) == 30.0
    assert scheduler.next_interval("ghost", 30.0) == 30.0


@pytest.mark.asyncio
async def test_run_all_due_defers_after_failure():
    """自动轮询：失败后按退避延后触发（只影响自动等待，不阻塞手动 run_once）"""
    calls: list[str] = []

    async def flaky() -> None:
        if not calls:
            calls.append("x")
            raise RuntimeError("boom")
        calls.append("x")

    scheduler = TaskScheduler(retry_backoff_base_seconds=30.0, max_retry_backoff_seconds=3600.0)
    scheduler.register_task(
        name="job:due", module="demo", interval_seconds=0.02, handler=flaky, consecutive_failure_limit=100
    )
    await scheduler.run_all_due()  # 到期执行：第 1 次失败，_last_run 已更新
    assert len(calls) == 1
    await scheduler.run_all_due()  # 间隔 0.02 + 退避 60s：未到期，不应触发
    assert len(calls) == 1
    # 手动触发不受退避影响
    assert await scheduler.run_once("job:due") is True
    assert len(calls) == 2
