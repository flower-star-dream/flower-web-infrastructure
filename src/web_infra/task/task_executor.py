"""
异步任务执行器

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 异步任务调度框架（规范 §9 异步化 / §23 任务执行记录 / §14.2 有界队列与拒绝策略 /
              §14.4 统一共享线程池）：优先主事件循环调度（FastAPI 场景），无运行循环时回退
              共享线程池（进程内单例，有界队列，满则拒绝）；任务状态机（PENDING→RUNNING→终态）
              与乐观锁终态保护（防并发覆盖）；心跳刷新与死任务扫描（心跳超时判定 DEAD，防僵尸任务）。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Coroutine

from web_infra.logging import get_logger
from web_infra.monitoring.runtime_metrics import ThreadPoolMetrics
from web_infra.task.shared_thread_pool import (
    RejectedExecutionError,
    SharedThreadPool,
    get_shared_thread_pool,
    shutdown_shared_pool,
)
from web_infra.task.task_record import TaskRecord
from web_infra.task.task_record_store import TaskRecordStoreInterface
from web_infra.task.task_status import TaskStatus

logger = get_logger("task.executor")

# 任务协程工厂：返回待执行协程
CoroFactory = Callable[[], Coroutine[Any, Any, Any]]

# 共享线程池的指标注册名（ThreadPoolMetrics 低基数标签，规范 §14.4 共享池单例）
_THREAD_POOL_NAME = "web-task"


class TaskExecutor:
    """异步任务执行器（事件循环优先 + 线程池回退）"""

    def __init__(
        self,
        record_store: TaskRecordStoreInterface,
        max_workers: int = 8,
        dead_threshold_seconds: float = 600,
        max_queue_size: int | None = None,
    ) -> None:
        """初始化任务执行器。

        :param record_store: 任务记录存储（SPI，默认内存实现）
        :param max_workers: 回退线程池最大线程数
        :param dead_threshold_seconds: 心跳超时阈值（秒），超过则判定任务死亡
        :param max_queue_size: 线程池任务队列上限（规范 §14.2 有界队列（峰值×2），
            None 默认 = max_workers × 2）；提交时队列已满抛 RejectedExecutionError
        """
        self._store = record_store
        self._dead_threshold_seconds = dead_threshold_seconds
        # 规范 §14.4 统一共享线程池：TaskExecutor 内部池即框架共享池（进程内单例），
        # 业务统一经 TaskExecutor/共享池提交，禁止自行 new ThreadPoolExecutor
        self._thread_pool: SharedThreadPool = get_shared_thread_pool(
            max_workers=max_workers, max_queue_size=max_queue_size
        )
        ThreadPoolMetrics.register(self._thread_pool, _THREAD_POOL_NAME)

    async def submit(self, coro_factory: CoroFactory, *, task_id: str | None = None, payload: dict[str, Any] | None = None) -> TaskRecord:
        """提交异步任务并在当前事件循环中调度执行（FastAPI 等异步场景）。

        :param coro_factory: 返回任务协程的工厂（延迟创建协程，便于捕获提交期异常）
        :param task_id: 自定义任务 ID（默认自动生成）
        :param payload: 任务元信息
        :return: 任务记录（初始 PENDING）
        """
        record = TaskRecord(task_id=task_id, payload=payload or {}) if task_id else TaskRecord(payload=payload or {})
        await self._store.save(record)
        asyncio.create_task(self._run(record, coro_factory))
        return record

    def submit_in_thread(self, coro_factory: CoroFactory, *, task_id: str | None = None, payload: dict[str, Any] | None = None) -> TaskRecord:
        """在同步上下文提交任务（后台脚本/测试等无事件循环场景），由共享线程池执行。

        提交前经有界队列 gate 检查（规范 §14.2 有界队列（峰值×2））：队列已满抛
        RejectedExecutionError（不阻塞调用方），调用方按拒绝策略自行处理（丢弃/降级/告警）。

        线程池任务协程运行在独立事件循环中：请勿在任务内触达 asyncio.Lock 保护的
        内存存储（缓存/幂等/outbox 等），asyncio.Lock 不跨线程互斥；应改用
        threading.Lock 或分布式实现（如 TaskRecordStore 内存实现已使用 threading.Lock）。

        :raises RejectedExecutionError: 任务队列已满拒绝执行
        :return: 任务记录（初始 PENDING；记录在任务启动时写入存储）
        """
        record = TaskRecord(task_id=task_id, payload=payload or {}) if task_id else TaskRecord(payload=payload or {})
        self._thread_pool.submit(self._run_in_thread, record, coro_factory)
        return record

    async def heartbeat(self, task_id: str) -> bool:
        """任务心跳刷新（任务协程内周期性调用，防被误判死亡）。

        :param task_id: 任务 ID
        :return: 是否刷新成功（任务非 RUNNING 或不存在时返回 False）
        """
        record = await self._store.load(task_id)
        if record is None or record.status is not TaskStatus.RUNNING:
            return False
        record.heartbeat_at = time.time()
        return await self._store.update(record)

    async def scan_dead_tasks(self) -> list[TaskRecord]:
        """扫描心跳超时的 RUNNING 任务并置为 DEAD（死任务回收）。

        :return: 本次判定死亡的任务列表
        """
        now = time.time()
        dead: list[TaskRecord] = []
        for record in await self._store.list_all():
            if record.status is not TaskStatus.RUNNING:
                continue
            last_beat = record.heartbeat_at or record.start_at or record.submit_at
            if now - last_beat > self._dead_threshold_seconds:
                record.status = TaskStatus.DEAD
                record.end_at = now
                record.error = "heartbeat timeout"
                if await self._store.update(record):
                    dead.append(record)
                    logger.warning("task_dead task_id=%s", record.task_id)
        return dead

    def close(self) -> None:
        """关闭共享线程池并注销监控（应用停机时调用，规范 §19.6 优雅停机 / §14.4）。

        关闭的是框架统一共享线程池（进程内单例），经共享池提交的未完成任务不再调度；
        下次获取共享池时自动重建新实例。
        """
        ThreadPoolMetrics.unregister(_THREAD_POOL_NAME)
        shutdown_shared_pool()

    # ------------------------------------------------------------------
    # 内部：任务执行
    # ------------------------------------------------------------------

    def _run_in_thread(self, record: TaskRecord, coro_factory: CoroFactory) -> None:
        """线程池回退执行入口：在线程内新建事件循环运行任务"""
        asyncio.run(self._run(record, coro_factory))

    async def _run(self, record: TaskRecord, coro_factory: CoroFactory) -> None:
        """执行任务：置 RUNNING → 运行协程 → 置终态（基于 store 最新记录 + 乐观锁终态保护）"""
        # 确保记录已写入存储（线程池回退路径在提交时不写库，启动时补写）
        current = await self._store.load(record.task_id)
        if current is None:
            await self._store.save(record)
            current = record
        if current.status is not TaskStatus.PENDING:
            return  # 非 PENDING（已被并发处理），放弃本次调度

        now = time.time()
        current.status = TaskStatus.RUNNING
        current.start_at = now
        current.heartbeat_at = now
        if not await self._store.update(current):
            logger.warning("task_start_conflict task_id=%s", current.task_id)
            return

        try:
            coro = coro_factory()
            await coro
            await self._mark_terminal(current.task_id, TaskStatus.SUCCESS)
        except Exception as e:
            logger.error("task_failed task_id=%s error=%s", current.task_id, str(e))
            await self._mark_terminal(current.task_id, TaskStatus.FAILED, error=str(e))

    async def _mark_terminal(self, task_id: str, status: TaskStatus, error: str = "") -> None:
        """置终态（SUCCESS/FAILED）：基于 store 最新记录，终态不可覆盖"""
        current = await self._store.load(task_id)
        if current is None or current.status.is_terminal:
            return
        current.status = status
        current.end_at = time.time()
        current.error = error
        await self._store.update(current)
