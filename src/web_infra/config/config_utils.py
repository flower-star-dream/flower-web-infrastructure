"""
配置工具

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 配置模块内部工具函数与常量（点分隔 key 嵌套读取、环境变量名转换、默认配置路径）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# 配置 Key 约定：点分隔（如 app.db.mysql.host），环境变量映射为大写 + 下划线（APP_DB_MYSQL_HOST）
_KEY_SEPARATOR = "."
_ENV_SEPARATOR = "_"

# 框架默认配置文件（包内，随发行包携带；配置统一走 YAML）
_DEFAULT_CONFIG_PATH = Path(__file__).parent / "application.default.yml"


def _get_nested(data: dict[str, Any], key: str, default: Any = None) -> Any:
    """按点分隔 key 从嵌套字典取值（优先匹配扁平 key，其次逐层下钻）"""
    if key in data:
        return data[key]
    current: Any = data
    for part in key.split(_KEY_SEPARATOR):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _contains_nested(data: dict[str, Any], key: str) -> bool:
    """判断嵌套字典是否含有点分隔 key"""
    if key in data:
        return True
    current: Any = data
    for part in key.split(_KEY_SEPARATOR):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _to_env_name(key: str, prefix: str = "") -> str:
    """将点分隔 key 转换为环境变量名（app.db.host -> APP_DB_HOST）"""
    return (prefix + key.replace(_KEY_SEPARATOR, _ENV_SEPARATOR)).upper()
