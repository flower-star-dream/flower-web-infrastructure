"""
服务注册发现接口

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 服务注册发现通用接口（SPI），遵循规范 §3（接口与扩展机制）与 §1.3 微服务适配。
              屏蔽 Nacos/Eureka/Consul 等注册中心差异，用户可自行实现替换，防止技术栈锁定。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from web_infra.capabilities.registry.service_instance import ServiceInstance


@runtime_checkable
class ServiceRegistryInterface(Protocol):
    """服务注册发现通用接口（SPI）"""

    async def register(self, service_name: str, instance: ServiceInstance) -> bool:
        """注册服务实例"""
        ...

    async def deregister(self, service_name: str, instance: ServiceInstance) -> bool:
        """注销服务实例"""
        ...

    async def get_instances(self, service_name: str) -> list[ServiceInstance]:
        """发现服务实例列表（仅健康实例）"""
        ...

    async def close(self) -> None:
        """释放底层资源"""
        ...
