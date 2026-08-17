"""
JSON 文件配置源

@Author: 花海
@Date: 2026/08/14 10:00
@Description: JSON 文件配置源（本地兜底方案，见附录 A.8），支持点分隔嵌套 key。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from web_infra.config.config_source_interface import ConfigSourceInterface
from web_infra.config.config_utils import _contains_nested, _get_nested


class JsonFileConfigSource(ConfigSourceInterface):
    """JSON 文件配置源（本地兜底方案，见附录 A.8），支持点分隔嵌套 key"""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._data: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        """延迟加载文件内容，避免无配置文件时报错"""
        if self._data is None:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            else:
                self._data = {}
        loaded = self._data
        assert loaded is not None
        return loaded

    def get(self, key: str, default: Any = None) -> Any:
        return _get_nested(self._load(), key, default)

    def contains(self, key: str) -> bool:
        return _contains_nested(self._load(), key)
