"""
Python 运行时与线程池指标采集模块

@Author: 花海
@Date: 2026/08/14 22:00
@Description: 采集 Python 运行时指标（GC 各代存活对象数、当前线程数，跨平台无额外依赖；
              prometheus-client 0.21+ 已内置 GC 累计计数器，此处仅补充缺失项）
              与线程池运行指标（工作线程/空闲线程/队列积压）。线程池通过 ThreadPoolMetrics 注册表
              （SPI 风格）注册后由 record_runtime_metrics 统一采样，业务可在创建线程池后一行注册。
"""
from __future__ import annotations

import gc
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import ClassVar

from prometheus_client import Gauge

logger = logging.getLogger(__name__)

# Python 运行时指标（python_ 前缀，规范 §18.5.4 运行时观测）
# 注：prometheus-client 0.21+ 已内置 python_gc_collections_total / python_gc_objects_collected_total /
#     python_gc_objects_uncollectable_total / python_info，此处仅补充内置缺失项（避免重名冲突）。
PYTHON_GC_LIVE_OBJECTS = Gauge("python_gc_live_objects", "Python GC 各代当前存活（被追踪）对象数", ["generation"])
PYTHON_THREADS_CURRENT = Gauge("python_threads_current", "当前活跃线程数")

# 线程池指标（thread_pool_ 前缀，name 为线程池注册名，低基数标签）
THREAD_POOL_WORKERS = Gauge("thread_pool_workers", "线程池当前工作线程数", ["name"])
THREAD_POOL_IDLE_WORKERS = Gauge("thread_pool_idle_workers", "线程池空闲线程数", ["name"])
THREAD_POOL_QUEUE_SIZE = Gauge("thread_pool_queue_size", "线程池任务队列积压数", ["name"])

# S16-3 静态集合治理：线程池注册表为静态无界容器，设置容量上限防止无界增长
# （业务侧异常场景反复注册不同 name 时不再无限累积）。
_MAX_POOLS = 100


class ThreadPoolMetrics:
    """线程池指标注册表（SPI 风格：业务将线程池注册后自动被采样展示）"""

    _pools: ClassVar[dict[str, ThreadPoolExecutor]] = {}
    # S16-3 静态集合治理：同一把锁保护注册/注销与采样遍历，collect 基于快照迭代，
    # 避免并发修改 dict 时迭代抛 RuntimeError（规范 §16.3 并发遍历需加锁/快照）。
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def register(cls, pool: ThreadPoolExecutor, name: str) -> ThreadPoolExecutor:
        """注册一个线程池（同名覆盖），返回原线程池便于链式调用。

        :param pool: ThreadPoolExecutor 实例
        :param name: 线程池注册名（低基数标签，如 "web-task"）
        :return: 传入的线程池
        """
        with cls._lock:
            # S16-3：静态容器有界，超过 _MAX_POOLS 上限拒绝新 name 注册（防无界增长）
            if name not in cls._pools and len(cls._pools) >= _MAX_POOLS:
                logger.warning("thread_pool_register_rejected name=%s limit=%d", name, _MAX_POOLS)
                return pool
            cls._pools[name] = pool
        return pool

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销线程池（线程池关闭时调用，防悬垂指标）"""
        with cls._lock:
            cls._pools.pop(name, None)

    @classmethod
    def collect(cls) -> None:
        """采样全部已注册线程池并写入 Gauge。

        依赖 ThreadPoolExecutor 私有属性（_threads/_idle_semaphore/_work_queue），
        不同 Python 版本属性可能变化，读取失败时该池指标按 0 处理。
        S16-3：锁内复制快照后锁外遍历，避免并发注册/注销时迭代抛 RuntimeError。
        """
        with cls._lock:
            pools = list(cls._pools.items())
        for name, pool in pools:
            try:
                workers = len(pool._threads)  # type: ignore[attr-defined]
                idle_semaphore = getattr(pool, "_idle_semaphore", None)
                idle = idle_semaphore._value if idle_semaphore is not None else 0  # type: ignore[attr-defined]
                queue_size = pool._work_queue.qsize()  # type: ignore[attr-defined]
            except Exception:
                workers = idle = queue_size = 0
            THREAD_POOL_WORKERS.labels(name).set(workers)
            THREAD_POOL_IDLE_WORKERS.labels(name).set(max(idle, 0))
            THREAD_POOL_QUEUE_SIZE.labels(name).set(queue_size)


def record_runtime_metrics() -> None:
    """采集 Python 运行时指标（各代存活对象数、当前线程数）。

    在 /metrics 抓取点调用；存活对象数按代统计（3.13 起 gc.get_objects 的
    generation 为 keyword-only，此处兼容 3.10+）。GC 统计异常不影响主流程。
    """
    try:
        for generation in range(3):
            try:
                objects = len(gc.get_objects(generation=generation))
            except TypeError:
                # 旧版本不支持按代统计，回退全量
                objects = len(gc.get_objects())
            PYTHON_GC_LIVE_OBJECTS.labels(str(generation)).set(objects)
    except Exception:
        pass  # GC 统计异常不影响主流程

    PYTHON_THREADS_CURRENT.set(threading.active_count())
