"""
Nacos 服务发现客户端

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 基于官方 nacos-sdk-python v2（gRPC）实现服务注册、注销与服务发现，
              实现 ServiceRegistryInterface SPI。临时实例由 SDK 自动心跳保活，无需手动发送心跳。
"""
from __future__ import annotations

from web_infra.capabilities.config.nacos_client_factory import build_client_config
from web_infra.capabilities.config.nacos_properties import NacosProperties
from web_infra.infra.logging import get_logger
from web_infra.infra.monitoring.registry_metrics import RegistryMetrics
from web_infra.capabilities.registry.service_instance import ServiceInstance
from web_infra.capabilities.registry.service_registry_interface import ServiceRegistryInterface

logger = get_logger("registry.nacos")


class NacosDiscoveryClient(ServiceRegistryInterface):
    """Nacos 服务发现客户端（官方 SDK gRPC，实现 ServiceRegistryInterface）"""

    def __init__(self, properties: NacosProperties) -> None:
        self.properties = properties
        self.group = properties.group
        self._naming_service = None

    async def _get_naming_service(self):
        """延迟创建并复用 NacosNamingService（首次调用时建立 gRPC 连接）"""
        if self._naming_service is None:
            from v2.nacos import NacosNamingService

            self._naming_service = await NacosNamingService.create_naming_service(
                build_client_config(self.properties)
            )
        return self._naming_service

    async def register(self, service_name: str, instance: ServiceInstance) -> bool:
        """注册服务实例到 Nacos（临时实例由 SDK 自动心跳保活）"""
        try:
            naming_service = await self._get_naming_service()
            from v2.nacos import RegisterInstanceParam

            ok = await naming_service.register_instance(
                RegisterInstanceParam(
                    service_name=service_name,
                    group_name=self.group,
                    ip=instance.ip,
                    port=instance.port,
                    weight=instance.weight,
                    metadata=instance.metadata,
                    healthy=instance.healthy,
                    enabled=True,
                    ephemeral=True,
                )
            )
            if ok:
                RegistryMetrics.record_register(service_name)
            return ok
        except Exception as e:
            logger.warning("nacos_register_failed service_name=%s error=%s", service_name, str(e))
            return False

    async def deregister(self, service_name: str, instance: ServiceInstance) -> bool:
        """从 Nacos 注销服务实例"""
        try:
            naming_service = await self._get_naming_service()
            from v2.nacos import DeregisterInstanceParam

            ok = await naming_service.deregister_instance(
                DeregisterInstanceParam(
                    service_name=service_name,
                    group_name=self.group,
                    ip=instance.ip,
                    port=instance.port,
                    ephemeral=True,
                )
            )
            if ok:
                RegistryMetrics.record_unregister(service_name)
            return ok
        except Exception as e:
            logger.warning("nacos_deregister_failed service_name=%s error=%s", service_name, str(e))
            return False

    async def get_instances(self, service_name: str) -> list[ServiceInstance]:
        """获取指定服务的健康实例列表"""
        try:
            naming_service = await self._get_naming_service()
            from v2.nacos import ListInstanceParam

            instances = await naming_service.list_instances(
                ListInstanceParam(
                    service_name=service_name,
                    group_name=self.group,
                    healthy_only=True,
                    subscribe=True,
                )
            )
            RegistryMetrics.record_discover(service_name)
            return [
                ServiceInstance(
                    ip=inst.ip,
                    port=inst.port,
                    weight=inst.weight,
                    metadata=inst.metadata,
                    healthy=inst.healthy,
                )
                for inst in instances
            ]
        except Exception as e:
            logger.warning("nacos_discovery_failed service_name=%s error=%s", service_name, str(e))
            return []

    async def close(self) -> None:
        """关闭命名服务连接，释放 gRPC 资源"""
        if self._naming_service is not None:
            try:
                await self._naming_service.shutdown()
            finally:
                self._naming_service = None
