"""
Nacos 配置加载器

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 从 Nacos 拉取 YAML 配置并解析为字典，与本地配置合并（远程配置优先级更高）。
"""
from __future__ import annotations

from typing import Any

import yaml

from web_infra.config.nacos_config_client import NacosConfigClient
from web_infra.config.nacos_properties import NacosProperties


class NacosConfigLoader:
    """Nacos 配置加载器：拉取 YAML 配置并与本地配置合并"""

    def __init__(self, properties: NacosProperties) -> None:
        self.properties = properties
        self.client = NacosConfigClient(properties)
        self._remote_config: dict[str, Any] = {}

    async def load(self, data_id: str | None = None, group: str | None = None) -> dict[str, Any]:
        """异步拉取并解析配置"""
        data_id = data_id or self.properties.data_id
        if not data_id:
            return {}
        config_str = await self.client.get_config(data_id, group)
        return self._parse(config_str)

    def load_sync(self, data_id: str | None = None, group: str | None = None) -> dict[str, Any]:
        """同步拉取并解析配置"""
        data_id = data_id or self.properties.data_id
        if not data_id:
            return {}
        config_str = self.client.get_config_sync(data_id, group)
        return self._parse(config_str)

    def _parse(self, config_str: str) -> dict[str, Any]:
        """解析 YAML 配置字符串"""
        if not config_str:
            return {}
        try:
            parsed = yaml.safe_load(config_str) or {}
            self._remote_config = parsed if isinstance(parsed, dict) else {}
            return self._remote_config
        except Exception:
            return {}

    def merge(self, local_config: dict[str, Any]) -> dict[str, Any]:
        """远程配置与本地配置合并，远程优先级更高"""
        return self._deep_merge(local_config, self._remote_config)

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """递归合并字典，override 优先级更高，忽略 None 值"""
        result = base.copy()
        for key, value in override.items():
            if value is None:
                continue
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = NacosConfigLoader._deep_merge(result[key], value)
            else:
                result[key] = value
        return result
