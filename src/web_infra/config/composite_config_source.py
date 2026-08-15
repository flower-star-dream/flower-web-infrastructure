"""
组合配置源

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 组合配置源：按传入顺序的优先级读取（越靠前优先级越高）。
"""
from __future__ import annotations

from typing import Any

from web_infra.config.config_source_interface import ConfigSourceInterface


class CompositeConfigSource(ConfigSourceInterface):
    """组合配置源：按传入顺序的优先级读取（越靠前优先级越高）"""

    def __init__(self, *sources: ConfigSourceInterface) -> None:
        self.sources = list(sources)

    def get(self, key: str, default: Any = None) -> Any:
        for source in self.sources:
            if source.contains(key):
                return source.get(key)
        return default

    def contains(self, key: str) -> bool:
        return any(source.contains(key) for source in self.sources)
