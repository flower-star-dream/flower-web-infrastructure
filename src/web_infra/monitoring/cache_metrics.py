"""
缓存组件指标采集器

@Author: 花海
@Date: 2026/08/14 23:30
@Description: 缓存组件（memory/redis）操作指标采集，懒注册模式：
              指标仅在组件实际被调用（启用）时注册到 REGISTRY，未启用组件不展现任何指标，
              由组件启用配置（app.cache.type）动态决定是否采集；
              组件关闭时调用 unregister_metrics() 卸载指标（规范 §16.5 扩展点注册与生命周期绑定）。
"""
from __future__ import annotations

from threading import Lock
from typing import ClassVar

from prometheus_client import REGISTRY, Counter

from web_infra.monitoring.component_metrics_interface import ComponentMetricsCollector


class CacheMetrics(ComponentMetricsCollector):
    """缓存组件指标采集器（懒注册：首次记录时注册指标）"""

    _registered: ClassVar[bool] = False
    # S16-2 豁免：临界区为纯内存操作，无 I/O 阻塞，不适用 3s 获取超时
    _lock: ClassVar[Lock] = Lock()

    operations_total: ClassVar[Counter | None] = None
    hits_total: ClassVar[Counter | None] = None
    misses_total: ClassVar[Counter | None] = None

    @classmethod
    def ensure(cls) -> None:
        """注册缓存指标（线程安全，仅首次执行）"""
        if cls._registered:
            return
        with cls._lock:
            if cls._registered:
                return
            cls.operations_total = Counter("cache_operations_total", "缓存操作次数", ["cache", "operation"])
            cls.hits_total = Counter("cache_hits_total", "缓存命中次数", ["cache"])
            cls.misses_total = Counter("cache_misses_total", "缓存未命中次数", ["cache"])
            cls._registered = True

    @classmethod
    def unregister_metrics(cls) -> None:
        """卸载缓存指标（组件关闭时调用，规范 §16.5 扩展点注册与生命周期绑定）。

        将 ensure() 注册的指标从 prometheus REGISTRY 移除并复位 _registered，
        使组件重启后 ensure() 可重新注册同名指标；指标已不存在时静默忽略。
        """
        with cls._lock:
            if not cls._registered:
                return
            for metric in (cls.operations_total, cls.hits_total, cls.misses_total):
                if metric is not None:
                    try:
                        REGISTRY.unregister(metric)
                    except KeyError:
                        # 指标已不在 REGISTRY（如被其他路径提前卸载），忽略
                        pass
            cls.operations_total = None
            cls.hits_total = None
            cls.misses_total = None
            cls._registered = False

    @classmethod
    def record_operation(cls, cache: str, operation: str, *, hit: bool | None = None) -> None:
        """记录一次缓存操作。

        :param cache: 缓存实现名（memory/redis，低基数标签）
        :param operation: 操作名（get/set/delete/exists）
        :param hit: 是否命中；get/exists 传 True/False，其余传 None
        """
        cls.ensure()
        operations = cls.operations_total
        assert operations is not None  # ensure() 已注册
        operations.labels(cache, operation).inc()
        if hit is True:
            hits = cls.hits_total
            assert hits is not None
            hits.labels(cache).inc()
        elif hit is False:
            misses = cls.misses_total
            assert misses is not None
            misses.labels(cache).inc()
