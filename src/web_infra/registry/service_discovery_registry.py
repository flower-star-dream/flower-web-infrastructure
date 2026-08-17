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

from threading import Lock
from typing import Callable, ClassVar

from web_infra.config import Settings
from web_infra.registry.service_registry_interface import ServiceRegistryInterface

#: 服务发现工厂签名：入参装配配置（Settings），返回服务注册发现实现
ServiceDiscoveryFactory = Callable[[Settings], ServiceRegistryInterface]


class ServiceDiscoveryRegistry:
    """服务发现注册表（类级注册，全局装配；同名覆盖）"""

    _factories: ClassVar[dict[str, ServiceDiscoveryFactory]] = {}
    _lock = Lock()

    @classmethod
    def register(cls, name: str, factory: ServiceDiscoveryFactory) -> None:
        """注册服务发现后端工厂（同名覆盖）。

        :param name: type 名（与 yml app.registry.type 匹配）
        :param factory: 工厂，入参 Settings，返回 ServiceRegistryInterface 实现
        """
        with cls._lock:
            cls._factories[name] = factory

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销后端（不存在时静默）"""
        with cls._lock:
            cls._factories.pop(name, None)

    @classmethod
    def get(cls, name: str) -> ServiceDiscoveryFactory:
        """按名查询工厂；未注册抛 KeyError（装配期由 create_app 捕获转 ConfigError）"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory

    @classmethod
    def create(cls, name: str, settings: Settings) -> ServiceRegistryInterface:
        """按名实例化服务发现后端；未注册抛 KeyError"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory(settings)

    @classmethod
    def registered_names(cls) -> list[str]:
        """已注册后端名清单"""
        with cls._lock:
            return list(cls._factories)


def _memory_registry_factory(settings: Settings) -> ServiceRegistryInterface:
    """内置 memory：内存服务注册发现（单机/测试场景）"""
    from web_infra.registry.in_memory import InMemoryServiceRegistry

    return InMemoryServiceRegistry(instance_expire_seconds=settings.get_int("app.registry.expire_seconds"))


def _nacos_registry_factory(settings: Settings) -> ServiceRegistryInterface:
    """内置 nacos：Nacos 服务注册发现（多实例/微服务场景）"""
    from web_infra.config.nacos_properties import NacosProperties
    from web_infra.registry.nacos_discovery import NacosDiscoveryClient

    config = NacosProperties(
        **{
            field: settings.get(f"app.registry.nacos.{field}")
            for field in NacosProperties.model_fields
            if settings.get(f"app.registry.nacos.{field}") is not None
        }
    )
    return NacosDiscoveryClient(config)


# 内置后端条目（模块导入即注册，幂等）
ServiceDiscoveryRegistry.register("memory", _memory_registry_factory)
ServiceDiscoveryRegistry.register("nacos", _nacos_registry_factory)
