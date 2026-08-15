"""
内存服务注册发现

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 内存服务注册发现实现（实现 ServiceRegistryInterface SPI），供单体/测试场景使用。
"""
from __future__ import annotations

import asyncio
import time

from web_infra.monitoring.registry_metrics import RegistryMetrics
from web_infra.registry.service_instance import ServiceInstance
from web_infra.registry.service_registry_interface import ServiceRegistryInterface


class InMemoryServiceRegistry(ServiceRegistryInterface):
    """内存服务注册发现实现（ServiceRegistryInterface SPI）

    @Stateful：进程内内存存储，单实例/单进程部署，多实例需替换为分布式实现（S1-1）。
    仅限单事件循环访问（asyncio.Lock 不跨线程互斥），跨线程/跨循环场景请改用线程安全或分布式实现。
    """

    def __init__(self, instance_expire_seconds: int = 15) -> None:
        self.instance_expire_seconds = instance_expire_seconds
        self._instances: dict[str, dict[str, tuple[ServiceInstance, float]]] = {}
        self._lock = asyncio.Lock()

    def _key(self, instance: ServiceInstance) -> str:
        """实例唯一标识"""
        return f"{instance.ip}:{instance.port}"

    async def register(self, service_name: str, instance: ServiceInstance) -> bool:
        async with self._lock:
            bucket = self._instances.setdefault(service_name, {})
            bucket[self._key(instance)] = (instance, time.monotonic())
            RegistryMetrics.record_register(service_name)
            return True

    async def deregister(self, service_name: str, instance: ServiceInstance) -> bool:
        async with self._lock:
            bucket = self._instances.get(service_name)
            if bucket is not None:
                bucket.pop(self._key(instance), None)
            RegistryMetrics.record_unregister(service_name)
            return True

    async def get_instances(self, service_name: str) -> list[ServiceInstance]:
        async with self._lock:
            bucket = self._instances.get(service_name, {})
            healthy: list[ServiceInstance] = []
            expire_at = time.monotonic() - self.instance_expire_seconds
            for key, (instance, last_seen) in list(bucket.items()):
                if last_seen >= expire_at:
                    healthy.append(instance)
                else:
                    bucket.pop(key, None)
            RegistryMetrics.record_discover(service_name)
            return healthy

    async def close(self) -> None:
        async with self._lock:
            self._instances.clear()

    def update_metrics(self) -> None:
        """刷新注册中心推送式指标（各服务在线实例数，供 /metrics 抓取调用）"""
        for service_name, bucket in self._instances.items():
            RegistryMetrics.update_instances(service_name, len(bucket))
