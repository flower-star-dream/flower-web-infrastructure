"""
环境变量配置源

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 环境变量配置源（敏感配置推荐注入方式，见附录 A.8）。
"""
from __future__ import annotations

import os
from typing import Any

from web_infra.infra.config.config_source_interface import ConfigSourceInterface
from web_infra.infra.config.config_utils import _to_env_name


class EnvConfigSource(ConfigSourceInterface):
    """环境变量配置源（敏感配置推荐注入方式，见附录 A.8）"""

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix

    def get(self, key: str, default: Any = None) -> Any:
        return os.environ.get(_to_env_name(key, self.prefix), default)

    def contains(self, key: str) -> bool:
        return _to_env_name(key, self.prefix) in os.environ
