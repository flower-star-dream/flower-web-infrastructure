"""
字典配置源

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 字典配置源（用于内置默认值与测试），支持点分隔嵌套 key。
"""
from __future__ import annotations

from typing import Any

from web_infra.config.config_source_interface import ConfigSourceInterface
from web_infra.config.config_utils import _contains_nested, _get_nested


class DictConfigSource(ConfigSourceInterface):
    """字典配置源（用于内置默认值与测试），支持点分隔嵌套 key"""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = data or {}

    def get(self, key: str, default: Any = None) -> Any:
        return _get_nested(self._data, key, default)

    def contains(self, key: str) -> bool:
        return _contains_nested(self._data, key)
