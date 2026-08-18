"""
YAML 文件配置源

@Author: 花海
@Date: 2026/08/14 10:00
@Description: YAML 文件配置源（需安装 pyyaml，见 extras[yaml]），延迟导入避免强制依赖。
              加载时解析 ${ENV_VAR} / ${ENV_VAR:default} 环境变量占位符，
              敏感配置（如数据库密码）可经环境变量注入，避免明文随 yml 提交仓库。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from web_infra.infra.config.config_source_interface import ConfigSourceInterface
from web_infra.infra.config.config_utils import (
    _contains_nested,
    _get_nested,
    resolve_env_placeholders,
)


class YamlConfigSource(ConfigSourceInterface):
    """YAML 文件配置源（需安装 pyyaml，见 extras[yaml]），延迟导入避免强制依赖"""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._data: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        """延迟加载 YAML 文件内容，并解析 ${ENV_VAR:default} 环境变量占位符"""
        if self._data is None:
            if os.path.exists(self.path):
                import yaml

                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = resolve_env_placeholders(yaml.safe_load(f) or {})
            else:
                self._data = {}
        loaded = self._data
        assert loaded is not None
        return loaded

    def get(self, key: str, default: Any = None) -> Any:
        return _get_nested(self._load(), key, default)

    def contains(self, key: str) -> bool:
        return _contains_nested(self._load(), key)
