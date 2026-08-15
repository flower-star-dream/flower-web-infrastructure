"""
Nacos 配置中心客户端

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 基于官方 nacos-sdk-python v2（gRPC）实现配置拉取，实现 ConfigClientInterface SPI。
              异步方法复用长连接；同步方法（get_config_sync）使用一次性事件循环 + 一次性连接，
              避免跨事件循环复用 SDK 连接导致异常。
"""
from __future__ import annotations

import asyncio

from web_infra.config.config_client_interface import ConfigClientInterface
from web_infra.config.nacos_client_factory import build_client_config
from web_infra.config.nacos_properties import NacosProperties
from web_infra.logging import get_logger

logger = get_logger("config.nacos")


class NacosConfigClient(ConfigClientInterface):
    """Nacos 配置中心客户端（官方 SDK gRPC，实现 ConfigClientInterface）"""

    def __init__(self, properties: NacosProperties) -> None:
        self.properties = properties
        self.group = properties.group
        self._config_service = None

    async def _get_service(self):
        """延迟创建并复用 NacosConfigService（首次调用时建立 gRPC 连接）"""
        if self._config_service is None:
            from v2.nacos import NacosConfigService

            self._config_service = await NacosConfigService.create_config_service(
                build_client_config(self.properties)
            )
        return self._config_service

    async def _get_config_once(self, data_id: str, group: str | None) -> str:
        """使用一次性 NacosConfigService 拉取配置（供同步方法使用，用完即关）"""
        from v2.nacos import ConfigParam, NacosConfigService

        service = await NacosConfigService.create_config_service(build_client_config(self.properties))
        try:
            return await service.get_config(ConfigParam(data_id=data_id, group=group or self.group))
        finally:
            await service.shutdown()

    async def get_config(self, data_id: str, group: str | None = None) -> str:
        """异步拉取配置内容"""
        try:
            service = await self._get_service()
            from v2.nacos import ConfigParam

            return await service.get_config(ConfigParam(data_id=data_id, group=group or self.group))
        except Exception as e:
            logger.warning("nacos_get_config_failed data_id=%s error=%s", data_id, str(e))
            return ""

    def get_config_sync(self, data_id: str, group: str | None = None) -> str:
        """同步拉取配置内容。

        仅可在无运行中事件循环的上下文调用（如应用启动阶段）；若处于事件循环内
        （如 async 函数中）请改用 get_config，否则会抛异常或阻塞。
        """
        try:
            asyncio.get_running_loop()
            logger.warning("nacos_get_config_sync_in_event_loop data_id=%s 请改用异步 get_config()", data_id)
            return ""
        except RuntimeError:
            pass
        try:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._get_config_once(data_id, group))
            finally:
                loop.close()
        except Exception as e:
            logger.warning("nacos_get_config_sync_failed data_id=%s error=%s", data_id, str(e))
            return ""

    async def close(self) -> None:
        """关闭配置中心连接，释放 gRPC 资源"""
        if self._config_service is not None:
            try:
                await self._config_service.shutdown()
            finally:
                self._config_service = None
