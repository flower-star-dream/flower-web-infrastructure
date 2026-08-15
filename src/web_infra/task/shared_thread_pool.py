"""
统一共享线程池

@Author: 花海
@Date: 2026/08/15
@Description: 框架统一共享线程池（规范 §14.4 统一共享线程池，禁止业务侧每次新建）：
              - 进程内单例：get_shared_thread_pool 懒创建（threading.Lock 保护），
                shutdown_shared_pool 显式关闭，关闭后自动重建新实例
              - 有界任务队列 + 拒绝策略（规范 §14.2 有界队列（峰值×2））：
                ThreadPoolExecutor 内部队列默认无界且不暴露 maxsize，此处用一个辅助
                有界 gate 队列（容量 = max_queue_size，默认 = 核心线程数 × 2）做提交前
                put_nowait 哨兵检查：队列已满抛 RejectedExecutionError，拒绝且不阻塞调用方
"""
from __future__ import annotations

import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

logger = logging.getLogger("web_infra.task.shared_pool")

# gate 队列占位哨兵（仅用于占位计名额，不承载业务数据）
_SLOT = object()


class RejectedExecutionError(RuntimeError):
    """任务队列已满拒绝执行，规范 §14.2 拒绝策略"""


class SharedThreadPool(ThreadPoolExecutor):
    """统一共享线程池：ThreadPoolExecutor + 有界队列 gate（提交前 put_nowait 检查，满则拒绝）"""

    def __init__(
        self,
        max_workers: int = 8,
        max_queue_size: int | None = None,
        thread_name_prefix: str = "web-task-",
    ) -> None:
        """初始化共享线程池。

        :param max_workers: 核心线程数（最大并发数）
        :param max_queue_size: 任务队列上限（规范 §14.2 有界队列（峰值×2）；
            None 默认 = max_workers × 2），提交时队列已满抛 RejectedExecutionError
        :param thread_name_prefix: 工作线程名前缀
        """
        super().__init__(max_workers=max_workers, thread_name_prefix=thread_name_prefix)
        queue_size = max_workers * 2 if max_queue_size is None else max_queue_size
        if queue_size <= 0:
            raise ValueError("max_queue_size 必须为正整数")
        # 有界 gate 队列：容量即任务队列上限，提交前 put_nowait 占位，worker 取走后释放
        self._gate: queue.Queue[object] = queue.Queue(maxsize=queue_size)
        self._max_queue_size = queue_size
        self._closed = False

    @property
    def max_queue_size(self) -> int:
        """任务队列上限（gate 容量）"""
        return self._max_queue_size

    @property
    def is_closed(self) -> bool:
        """线程池是否已关闭（关闭后经 get_shared_thread_pool 会自动重建）"""
        return self._closed

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        """有界提交：队列满抛 RejectedExecutionError，不阻塞调用方（规范 §14.2 拒绝策略）。

        :param fn: 待执行函数
        :raises RejectedExecutionError: 任务队列已满拒绝执行
        :raises RuntimeError: 线程池已关闭后提交
        """
        if self._closed:
            raise RuntimeError("cannot schedule new futures after shutdown")
        try:
            self._gate.put_nowait(_SLOT)
        except queue.Full:
            raise RejectedExecutionError(
                f"任务队列已满（上限 {self._max_queue_size}），拒绝执行（规范 §14.2 拒绝策略）"
            ) from None
        try:
            return super().submit(self._run_guarded, fn, args, kwargs)
        except BaseException:
            # 提交失败（如提交瞬间池被关闭）：释放已占用的名额，避免名额泄漏
            try:
                self._gate.get_nowait()
            except queue.Empty:
                pass
            raise

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        """关闭线程池（标记 closed 后拒绝新提交，经共享池入口自动重建）"""
        self._closed = True
        super().shutdown(wait=wait, cancel_futures=cancel_futures)

    def _run_guarded(self, fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        """工作线程入口：任务已被 worker 取走，先释放 gate 名额，再执行用户函数"""
        try:
            self._gate.get_nowait()
        except queue.Empty:
            pass
        return fn(*args, **kwargs)


_pool: SharedThreadPool | None = None
_pool_lock = threading.Lock()


def get_shared_thread_pool(max_workers: int = 8, max_queue_size: int | None = None) -> SharedThreadPool:
    """获取进程内共享线程池单例（规范 §14.4 统一共享线程池，禁止业务侧每次新建）。

    threading.Lock 保护懒创建：首次调用决定 max_workers/max_queue_size，后续调用
    复用同一实例（参数仅首次生效）；池被关闭后自动重建新实例。

    :param max_workers: 核心线程数（首次创建生效）
    :param max_queue_size: 任务队列上限（规范 §14.2，None 默认 = max_workers × 2）
    :return: 共享线程池单例
    """
    global _pool
    if _pool is None or _pool.is_closed:
        with _pool_lock:
            if _pool is None or _pool.is_closed:
                _pool = SharedThreadPool(max_workers=max_workers, max_queue_size=max_queue_size)
                logger.info(
                    "shared_thread_pool_created max_workers=%s max_queue_size=%s",
                    max_workers, _pool.max_queue_size,
                )
    return _pool


def shutdown_shared_pool() -> None:
    """显式关闭共享线程池（应用停机时调用，规范 §14.4 / §19.6 优雅停机）；关闭后自动重建"""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown(wait=False)
            _pool = None
            logger.info("shared_thread_pool_shutdown")
