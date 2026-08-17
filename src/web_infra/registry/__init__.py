"""
服务注册发现模块

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 服务注册发现能力，遵循规范 §3（SPI）与 §1.3 微服务适配。
              提供 ServiceRegistryInterface SPI + Nacos（HTTP API）/ 内存实现，用户可自行实现替换注册中心。
"""
from web_infra.registry.service_instance import ServiceInstance
from web_infra.registry.service_registry_interface import ServiceRegistryInterface
from web_infra.registry.nacos_discovery import NacosDiscoveryClient
from web_infra.registry.nacos_registration import NacosRegistration
from web_infra.registry.in_memory import InMemoryServiceRegistry
from web_infra.registry.service_discovery_registry import ServiceDiscoveryRegistry

__all__ = [
    "ServiceInstance",
    "ServiceRegistryInterface",
    "NacosDiscoveryClient",
    "NacosRegistration",
    "InMemoryServiceRegistry",
    "ServiceDiscoveryRegistry",
]
