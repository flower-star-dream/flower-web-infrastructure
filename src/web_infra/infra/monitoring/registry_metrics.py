"""
服务注册中心组件指标采集器

@Author: 花海
@Date: 2026/08/14 23:30
@Description: 服务注册发现组件（memory/nacos）指标采集，懒注册模式：
              指标仅在组件实际被调用（启用）时注册，未启用组件不展现任何指标，
              由组件启用配置（app.registry.type）动态决定是否采集。
              实例数（instances）为 Gauge，由组件 update_metrics 在 /metrics 抓取时刷新。
"""
from __future__ import annotations

from threading import Lock
from typing import ClassVar

from prometheus_client import Counter, Gauge

from web_infra.infra.monitoring.component_metrics_interface import ComponentMetricsCollector


class RegistryMetrics(ComponentMetricsCollector):
    """服务注册中心组件指标采集器（懒注册：首次记录时注册指标）"""

    _registered: ClassVar[bool] = False
    # S16-2 豁免：临界区为纯内存操作，无 I/O 阻塞，不适用 3s 获取超时
    _lock: ClassVar[Lock] = Lock()

    register_total: ClassVar[Counter | None] = None
    unregister_total: ClassVar[Counter | None] = None
    discover_total: ClassVar[Counter | None] = None
    instances: ClassVar[Gauge | None] = None

    @classmethod
    def ensure(cls) -> None:
        """注册服务注册中心指标（线程安全，仅首次执行）"""
        if cls._registered:
            return
        with cls._lock:
            if cls._registered:
                return
            cls.register_total = Counter("registry_register_total", "服务注册次数", ["service"])
            cls.unregister_total = Counter("registry_unregister_total", "服务注销次数", ["service"])
            cls.discover_total = Counter("registry_discover_total", "服务发现查询次数", ["service"])
            cls.instances = Gauge("registry_instances", "服务在线实例数", ["service"])
            cls._registered = True

    @classmethod
    def record_register(cls, service: str) -> None:
        """记录一次服务注册"""
        cls.ensure()
        counter = cls.register_total
        assert counter is not None  # ensure() 已注册
        counter.labels(service).inc()

    @classmethod
    def record_unregister(cls, service: str) -> None:
        """记录一次服务注销"""
        cls.ensure()
        counter = cls.unregister_total
        assert counter is not None
        counter.labels(service).inc()

    @classmethod
    def record_discover(cls, service: str) -> None:
        """记录一次服务发现查询"""
        cls.ensure()
        counter = cls.discover_total
        assert counter is not None
        counter.labels(service).inc()

    @classmethod
    def update_instances(cls, service: str, count: int) -> None:
        """刷新指定服务的在线实例数（组件 update_metrics 调用）"""
        cls.ensure()
        instances = cls.instances
        assert instances is not None
        instances.labels(service).set(max(count, 0))
