"""
服务发现注册表

@Author: 花海
@Date: 2026/08/17 17:00
@Description: 服务注册发现 SPI 注册表：按 type 名注册/查询 ServiceRegistryInterface 工厂，
              装配期（app.registry.type）按名实例化；内置 memory/nacos 条目，
              用户自定义注册中心（Consul/Eureka 等）经 register 注册后即可接入 create_app，
              无需改动框架装配代码；未注册的 type 装配期快速失败（ConfigError）。
"""
from __future__ import annotations

from typing import Callable

from web_infra.capabilities.registry.service_registry_interface import ServiceRegistryInterface
from web_infra.core.spi import SpiRegistry
from web_infra.infra.config import Settings

#: 服务发现工厂签名：入参装配配置（Settings），返回服务注册发现实现
ServiceDiscoveryFactory = Callable[[Settings], ServiceRegistryInterface]


class ServiceDiscoveryRegistry(SpiRegistry):
    """服务发现注册表（SpiRegistry 基类：命名空间隔离 + 内置默认保护；同名覆盖默认拒绝）"""

    @classmethod
    def create(cls, name: str, settings: Settings) -> ServiceRegistryInterface:
        """按名实例化服务发现后端；未注册抛 KeyError"""
        return cls.get(name)(settings)


def _memory_registry_factory(settings: Settings) -> ServiceRegistryInterface:
    """内置 memory：内存服务注册发现（单机/测试场景）"""
    from web_infra.capabilities.registry.in_memory import InMemoryServiceRegistry

    return InMemoryServiceRegistry(instance_expire_seconds=settings.get_int("app.registry.expire_seconds") or 15)


def _nacos_registry_factory(settings: Settings) -> ServiceRegistryInterface:
    """内置 nacos：Nacos 服务注册发现（多实例/微服务场景）"""
    from web_infra.capabilities.config.nacos_properties import NacosProperties
    from web_infra.capabilities.registry.nacos_discovery import NacosDiscoveryClient

    config = NacosProperties(
        **{
            field: settings.get(f"app.registry.nacos.{field}")
            for field in NacosProperties.model_fields
            if settings.get(f"app.registry.nacos.{field}") is not None
        }
    )
    return NacosDiscoveryClient(config)


# 内置后端条目（模块导入即注册，幂等；落框架命名空间，受保护）
ServiceDiscoveryRegistry.register("memory", _memory_registry_factory, namespace=ServiceDiscoveryRegistry.FRAMEWORK_NAMESPACE)
ServiceDiscoveryRegistry.register("nacos", _nacos_registry_factory, namespace=ServiceDiscoveryRegistry.FRAMEWORK_NAMESPACE)
