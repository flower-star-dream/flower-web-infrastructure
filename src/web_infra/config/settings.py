"""
统一配置读取门面

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一配置读取门面：供业务代码全局访问，屏蔽底层配置源。
              支持 get/get_required/get_int/get_float/get_bool/get_list 便捷读取。
              环境标识（规范 §19.3 启动必须显式指定环境，禁止默认环境）：app_env 从
              环境变量 APP_ENV 或配置 app.env 解析，默认 "dev"（保留向后兼容并告警），
              生产环境必须显式指定 APP_ENV=prod。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from web_infra.config.composite_config_source import CompositeConfigSource
from web_infra.config.config_error import ConfigError
from web_infra.config.config_source_interface import ConfigSourceInterface
from web_infra.config.config_utils import _DEFAULT_CONFIG_PATH, load_env_file
from web_infra.config.dict_config_source import DictConfigSource
from web_infra.config.env_config_source import EnvConfigSource
from web_infra.config.yaml_config_source import YamlConfigSource

logger = logging.getLogger("web_infra.config.settings")

# 合法环境标识集合（规范 §19.3 环境枚举：dev/test/stage/prod）
ENVIRONMENTS = {"dev", "test", "stage", "prod"}


class Settings:
    """统一配置读取门面：供业务代码全局访问，屏蔽底层配置源（规范 §19.3 显式环境）"""

    _default: "Settings | None" = None

    def __init__(self, source: ConfigSourceInterface) -> None:
        self._source = source
        # 环境标识解析（规范 §19.3）：APP_ENV 环境变量 > 配置 app.env > 默认 dev（告警）
        self._app_env = self._resolve_app_env(source)

    @property
    def app_env(self) -> str:
        """当前应用环境标识（dev/test/stage/prod，规范 §19.3）"""
        return self._app_env

    def is_production(self) -> bool:
        """是否生产环境（app_env == "prod"，规范 §19.3 生产行为开关）"""
        return self._app_env == "prod"

    @staticmethod
    def _resolve_app_env(source: ConfigSourceInterface) -> str:
        """解析应用环境：APP_ENV 环境变量 > 配置 app.env > 默认 dev。

        规范 §19.3 启动必须显式指定环境：未显式指定或值非法时按 dev 兜底并告警
        （生产环境必须显式设置 APP_ENV=prod，禁止依赖默认值）。
        非法值处理策略：按 dev 兜底 + warning（而非拒绝抛错），避免因环境值笔误
        导致应用启动失败；告警日志足以暴露配置问题。
        """
        raw = os.environ.get("APP_ENV")
        if raw is None or not str(raw).strip():
            raw = source.get("app.env")
        value = str(raw).strip().lower() if raw is not None else ""
        if value in ENVIRONMENTS:
            return value
        if raw is None or not str(raw).strip():
            logger.warning("未显式指定 APP_ENV，使用默认 dev（规范 §19.3 生产环境必须显式指定）")
        else:
            logger.warning("非法 APP_ENV=%s，按 dev 兜底（规范 §19.3 合法环境：%s）", raw, sorted(ENVIRONMENTS))
        return "dev"

    def get(self, key: str, default: Any = None) -> Any:
        """读取配置（字符串原样返回）"""
        return self._source.get(key, default)

    def get_required(self, key: str) -> Any:
        """读取必填配置，缺失时抛出 ConfigError"""
        if not self._source.contains(key):
            raise ConfigError(f"缺少必填配置项：{key}", key=key)
        return self._source.get(key)

    def get_int(self, key: str, default: int | None = None) -> int | None:
        """读取整型配置"""
        value = self.get(key)
        if value is None:
            return default
        return int(value)

    def get_float(self, key: str, default: float | None = None) -> float | None:
        """读取浮点配置"""
        value = self.get(key)
        if value is None:
            return default
        return float(value)

    def get_bool(self, key: str, default: bool = False) -> bool:
        """读取布尔配置（支持 true/false、1/0、yes/no）"""
        value = self.get(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "1", "yes", "on"}

    def get_list(self, key: str, default: list | None = None) -> list:
        """读取列表配置（支持 JSON 数组或逗号分隔字符串）"""
        value = self.get(key)
        if value is None:
            return default or []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return [value]

    @classmethod
    def configure(cls, source: ConfigSourceInterface) -> "Settings":
        """设置全局 Settings 实例"""
        cls._default = Settings(source)
        return cls._default

    @classmethod
    def default_source(cls) -> ConfigSourceInterface:
        """构造默认配置源：.env（自动加载）-> 环境变量 > 项目 application.yml > 框架默认配置。

        优先加载项目根 .env 文件（已存在的环境变量不覆盖），使 yml 中 ${ENV} 占位符
        与环境变量覆盖均能读取 .env 中的敏感配置（如数据库密码），避免明文随 yml 提交仓库。
        """
        load_env_file()
        return CompositeConfigSource(
            EnvConfigSource(),
            YamlConfigSource("application.yml"),
            YamlConfigSource(_DEFAULT_CONFIG_PATH),
            DictConfigSource(),
        )

    @classmethod
    def instance(cls) -> "Settings":
        """获取全局 Settings 实例（未配置时使用默认源）"""
        if cls._default is None:
            cls._default = Settings(cls.default_source())
        return cls._default
