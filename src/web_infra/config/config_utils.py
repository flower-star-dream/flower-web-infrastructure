"""
配置工具

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 配置模块内部工具函数与常量（点分隔 key 嵌套读取、环境变量名转换、
              环境变量占位符解析、.env 文件加载、默认配置路径）。
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("web_infra.config")

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


# 环境变量占位符正则：${ENV_VAR} 或 ${ENV_VAR:default}
_ENV_PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


def _replace_env_placeholders(value: str) -> str:
    """替换字符串中的 ${ENV_VAR} / ${ENV_VAR:default} 环境变量占位符。

    环境变量已定义时取其值；未定义时取默认值；未定义且无默认值时保留原样。
    """
    def replacer(match: re.Match) -> str:
        env_value = os.environ.get(match.group(1))
        if env_value is not None:
            return env_value
        return match.group(2) if match.group(2) is not None else match.group(0)

    return _ENV_PLACEHOLDER_PATTERN.sub(replacer, value)


def resolve_env_placeholders(data: Any) -> Any:
    """递归解析配置中的 ${ENV_VAR} / ${ENV_VAR:default} 环境变量占位符（dict/list/str）"""
    if isinstance(data, dict):
        return {k: resolve_env_placeholders(v) for k, v in data.items()}
    if isinstance(data, list):
        return [resolve_env_placeholders(item) for item in data]
    if isinstance(data, str):
        return _replace_env_placeholders(data)
    return data


def load_env_file(dotenv_path: str | Path | None = None) -> bool:
    """加载项目根 .env 文件到环境变量（敏感配置本地注入，避免随 yml 提交仓库）。

    默认加载当前工作目录下的 .env（启动命令约定在项目根目录执行）；
    已存在的环境变量优先（override=False，不覆盖进程级/容器注入的变量）。
    python-dotenv 为可选依赖：未安装时输出 warning 并返回 False，不影响配置读取。
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        logger.warning("未安装 python-dotenv，跳过 .env 文件加载（pip install python-dotenv）")
        return False
    return load_dotenv(dotenv_path=dotenv_path or ".env", override=False, verbose=False)
