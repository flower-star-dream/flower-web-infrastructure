"""
对象存储组件指标采集器

@Author: 花海
@Date: 2026/08/14 23:30
@Description: 对象存储组件（local/minio）操作指标采集，懒注册模式：
              指标仅在组件实际被调用（启用）时注册，未启用组件不展现任何指标，
              由组件启用配置（app.storage.type）动态决定是否采集。
"""
from __future__ import annotations

from threading import Lock
from typing import ClassVar

from prometheus_client import Counter

from web_infra.monitoring.component_metrics_interface import ComponentMetricsCollector


class StorageMetrics(ComponentMetricsCollector):
    """对象存储组件指标采集器（懒注册：首次记录时注册指标）"""

    _registered: ClassVar[bool] = False
    # S16-2 豁免：临界区为纯内存操作，无 I/O 阻塞，不适用 3s 获取超时
    _lock: ClassVar[Lock] = Lock()

    operations_total: ClassVar[Counter | None] = None
    bytes_total: ClassVar[Counter | None] = None

    @classmethod
    def ensure(cls) -> None:
        """注册对象存储指标（线程安全，仅首次执行）"""
        if cls._registered:
            return
        with cls._lock:
            if cls._registered:
                return
            cls.operations_total = Counter("storage_operations_total", "对象存储操作次数", ["storage", "operation"])
            cls.bytes_total = Counter("storage_bytes_total", "对象存储传输字节数", ["storage", "operation"])
            cls._registered = True

    @classmethod
    def record_operation(cls, storage: str, operation: str, *, bytes_count: int = 0) -> None:
        """记录一次对象存储操作。

        :param storage: 存储实现名（local/minio，低基数标签）
        :param operation: 操作名（put/get/delete/exists）
        :param bytes_count: 本次读写字节数（put/get 传入，其余为 0）
        """
        cls.ensure()
        operations = cls.operations_total
        assert operations is not None  # ensure() 已注册
        operations.labels(storage, operation).inc()
        if bytes_count > 0:
            bytes_total = cls.bytes_total
            assert bytes_total is not None
            bytes_total.labels(storage, operation).inc(bytes_count)
