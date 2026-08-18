"""
定时任务调度器

@Author: 花海
@Date: 2026/08/14 18:00
@Description: asyncio 定时任务调度器（规范 §23）：
              - 任务注册：唯一标识 + 模块归属 + 间隔 + 描述（§23.1 禁止匿名任务）
              - 多实例防重复：可选分布式锁工厂（§23.2 单实例执行，锁带租约自动释放）
              - 执行超时中断（§23.3）、禁止重叠、连续失败自动暂停告警（§23.4）
              - 执行可观测：开始/结束/失败/耗时写入日志（§23.1 与日志/指标联动）
              - 执行记录持久化（整改 S23-1）：可选注入 record_store（复用 web_infra.capabilities.task
                TaskRecordStoreInterface），每次执行写入 TaskRecord（任务名/触发时间/耗时/
                结果/失败原因），满足审计留存 ≥90 天；未注入则不记录，向后兼容
              - 锁竞争超时跳过本轮（整改 S23-2）：tryLock 超时（TimeoutError）记为跳过
                而非失败，不累计连续失败、不触发误暂停
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import AsyncExitStack
from typing import Any, Callable

from web_infra.capabilities.schedule.scheduled_task import ScheduledTask
from web_infra.capabilities.task.task_record import TaskRecord
from web_infra.capabilities.task.task_record_store import TaskRecordStoreInterface
from web_infra.capabilities.task.task_status import TaskStatus

logger = logging.getLogger("web_infra.capabilities.schedule")


class TaskScheduler:
    """asyncio 定时任务调度器（单实例默认，可选分布式锁防多实例重复执行）"""

    def __init__(
        self,
        lock_factory: Callable[[str], Any] | None = None,
        tick_seconds: float = 0.5,
        record_store: TaskRecordStoreInterface | None = None,
        retry_backoff_base_seconds: float = 30.0,
        max_retry_backoff_seconds: float = 3600.0,
    ) -> None:
        """初始化调度器。

        :param lock_factory: 分布式锁工厂 `(task_name) -> 异步上下文管理器`（规范 §23.2，
            提供时多实例仅单实例执行；None 表示单实例场景不取锁）
        :param tick_seconds: 调度循环轮询间隔（秒）
        :param record_store: 任务执行记录存储（SPI，规范 §23.4 审计留存 ≥90 天，
            复用 web_infra.capabilities.task 的 TaskRecordStoreInterface；None 表示不记录，向后兼容）
        :param retry_backoff_base_seconds: 失败退避基数（秒，规范 §23.3 退避间隔），
            连续失败 n 次后的退避 = min(基数 × 2^n, 上限)
        :param max_retry_backoff_seconds: 失败退避上限（秒，规范 §23.3 退避封顶）
        """
        self._tasks: dict[str, ScheduledTask] = {}
        self._last_run: dict[str, float] = {}
        self._consecutive_failures: dict[str, int] = {}
        self._paused: set[str] = set()
        self._lock_factory = lock_factory
        self._tick_seconds = tick_seconds
        self._record_store = record_store
        self._retry_backoff_base_seconds = retry_backoff_base_seconds
        self._max_retry_backoff_seconds = max_retry_backoff_seconds
        self._loop_task: asyncio.Task | None = None
        self._running = False

    def register(self, task: ScheduledTask) -> None:
        """注册定时任务（重复 name 覆盖，规范 §23.1 唯一标识约束）"""
        if not task.name or not task.module or task.interval_seconds <= 0:
            raise ValueError("任务 name/module/interval_seconds 均为必填且间隔须大于 0")
        if task.name in self._tasks:
            logger.warning("scheduled_task_replaced name=%s", task.name)
        self._tasks[task.name] = task
        self._last_run[task.name] = 0.0
        self._consecutive_failures[task.name] = 0

    def register_task(
        self,
        name: str,
        module: str,
        interval_seconds: float,
        handler: Any,
        *,
        description: str = "",
        timeout_seconds: float | None = None,
        consecutive_failure_limit: int = 3,
    ) -> None:
        """便捷注册：按参数构造 ScheduledTask 并注册"""
        self.register(
            ScheduledTask(
                name=name,
                module=module,
                interval_seconds=interval_seconds,
                handler=handler,
                description=description,
                timeout_seconds=timeout_seconds,
                consecutive_failure_limit=consecutive_failure_limit,
            )
        )

    def is_paused(self, name: str) -> bool:
        """任务是否处于暂停状态（连续失败触发）"""
        return name in self._paused

    def resume(self, name: str) -> None:
        """手动恢复暂停的任务（连续失败自动暂停后由运维介入恢复）"""
        self._paused.discard(name)
        self._consecutive_failures[name] = 0

    def start(self) -> None:
        """启动调度循环（后台任务，需在运行中的事件循环内调用）"""
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._schedule_loop())

    async def stop(self) -> None:
        """停止调度循环并等待退出"""
        self._running = False
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

    async def run_once(self, name: str) -> bool:
        """手动触发执行指定任务一次（不等待间隔），返回是否执行成功"""
        task = self._tasks.get(name)
        if task is None:
            raise KeyError(f"未注册任务: {name}")
        return await self._execute(task)

    async def run_all_due(self) -> None:
        """执行当前全部到期任务（测试与手动触发用）。

        到期判断叠加失败退避（规范 §23.3）：连续失败的任务按 next_interval
        延后自动触发，成功执行后回到原间隔。
        """
        now = time.monotonic()
        for task in list(self._tasks.values()):
            interval = self.next_interval(task.name, task.interval_seconds)
            due = now - self._last_run.get(task.name, 0.0) >= interval
            if due:
                await self._execute(task)
                self._last_run[task.name] = time.monotonic()

    def next_interval(self, task_name: str, base_interval: float) -> float:
        """计算任务下一次自动触发间隔：原间隔 + 指数退避（规范 §23.3 重试次数上限与退避间隔）。

        连续失败 n 次后的退避 = min(退避基数 × 2^n, 退避上限)；成功执行清零后回到原间隔。
        仅用于调度循环自动等待下一轮（run_all_due 到期判断），手动 run_once 不受影响；
        若调度框架复用本调度器（无自动 loop 场景），外部可直接调用本方法接入退避。

        :param task_name: 任务名（连续失败次数按任务名隔离记录）
        :param base_interval: 任务原始调度间隔（秒）
        :return: 下一次自动触发间隔（秒）
        """
        failures = self._consecutive_failures.get(task_name, 0)
        if failures <= 0:
            return base_interval
        backoff = min(
            self._retry_backoff_base_seconds * (2 ** failures),
            self._max_retry_backoff_seconds,
        )
        return base_interval + backoff

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _schedule_loop(self) -> None:
        """调度主循环：轮询到期任务（禁止重叠，超时未获锁跳过本轮，规范 §23.2）"""
        while self._running:
            await self.run_all_due()
            await asyncio.sleep(self._tick_seconds)

    async def _execute(self, task: ScheduledTask) -> bool:
        """执行单个任务：分布式锁 -> 超时控制 -> 结果记录 -> 连续失败暂停。

        结果语义：成功返回 True；失败/跳过返回 False。
        锁获取超时（tryLock 竞争，规范 §23.2）记为跳过：不累计连续失败、不记录失败原因、
        不触发误暂停（整改 S23-2）；执行超时（§23.3）仍计为失败。
        """
        wall_start = time.time()
        if task.name in self._paused:
            logger.warning("scheduled_task_skipped_paused name=%s", task.name)
            await self._record_execution(task, wall_start, TaskStatus.SKIPPED, "task paused")
            return False
        started = time.monotonic()
        lock_acquired = False
        try:
            async with AsyncExitStack() as stack:
                if self._lock_factory is not None:
                    lock = self._lock_factory(task.name)
                    await stack.enter_async_context(lock)
                    lock_acquired = True
                coro = task.handler()
                if task.timeout_seconds is not None:
                    await asyncio.wait_for(coro, timeout=task.timeout_seconds)
                else:
                    await coro
        except (asyncio.TimeoutError, TimeoutError) as exc:
            if self._lock_factory is not None and not lock_acquired:
                # 锁获取超时（分布式锁竞争，规范 §23.2）：跳过本轮，不累计连续失败
                logger.warning(
                    "scheduled_task_skipped_lock name=%s module=%s reason=%s",
                    task.name, task.module, exc,
                )
                await self._record_execution(task, wall_start, TaskStatus.SKIPPED, "lock timeout")
                return False
            reason = f"timeout after {task.timeout_seconds}s"
            self._record_failure(task, started, reason)
            await self._record_execution(task, wall_start, TaskStatus.FAILED, reason)
            return False
        except Exception as exc:  # noqa: BLE001 - 定时任务异常统一记录并暂停治理
            reason = str(exc)
            self._record_failure(task, started, reason)
            await self._record_execution(task, wall_start, TaskStatus.FAILED, reason)
            return False
        self._consecutive_failures[task.name] = 0
        logger.info(
            "scheduled_task_done name=%s module=%s duration_ms=%s",
            task.name, task.module, int((time.monotonic() - started) * 1000),
        )
        await self._record_execution(task, wall_start, TaskStatus.SUCCESS)
        return True

    def _record_failure(self, task: ScheduledTask, started: float, reason: str) -> None:
        """记录失败：累计连续失败，达阈值自动暂停（规范 §23.4 连续失败告警并降频/暂停）"""
        failures = self._consecutive_failures.get(task.name, 0) + 1
        self._consecutive_failures[task.name] = failures
        logger.error(
            "scheduled_task_failed name=%s module=%s duration_ms=%s reason=%s failures=%s",
            task.name, task.module, int((time.monotonic() - started) * 1000), reason, failures,
        )
        if failures >= task.consecutive_failure_limit:
            self._paused.add(task.name)
            logger.error("scheduled_task_paused name=%s failures=%s", task.name, failures)

    async def _record_execution(
        self,
        task: ScheduledTask,
        start_wall: float,
        status: TaskStatus,
        reason: str = "",
    ) -> None:
        """写入调度执行记录（任务名/触发时间/耗时/结果/失败原因，规范 §23.4 审计留存 ≥90 天）。

        与 TaskRecord 字段映射（整改 S23-1）：task_id 默认自动生成，每次执行一条独立记录
        （保留执行历史，避免按 name 覆盖）；任务名/模块写入 payload（task_name/module）；
        submit_at/start_at 为本次触发时间（unix 秒），end_at 为记录写入时刻，
        duration_seconds 由 start/end 自动计算；SKIPPED 不视为失败，error 仅记录跳过原因
        （如 lock timeout / task paused）。写入失败仅告警，不影响任务自身执行结果。
        """
        if self._record_store is None:
            return
        try:
            record = TaskRecord(
                status=status,
                submit_at=start_wall,
                start_at=start_wall,
                end_at=time.time(),
                error=reason,
                payload={"task_name": task.name, "module": task.module},
            )
            await self._record_store.save(record)
        except Exception as exc:  # noqa: BLE001 - 记录写入失败不应影响任务执行
            logger.warning("scheduled_task_record_failed name=%s error=%s", task.name, exc)
