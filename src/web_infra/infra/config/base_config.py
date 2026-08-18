"""
配置基类

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 基于 pydantic-settings 的配置基类，支持 YAML 多环境 profile、环境变量/属性占位符解析、
              Nacos 配置中心合并，遵循规范 §15.2 配置安全。子类继承后声明嵌套配置字段即可。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from web_infra.infra.config.config_utils import resolve_env_placeholders
from web_infra.capabilities.config.nacos_properties import NacosProperties


class BaseConfig(BaseSettings):
    """配置基类：所有服务配置继承此类"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
        case_sensitive=False,
    )

    @classmethod
    def from_yaml_with_profile(
        cls,
        config_dir: str | Path,
        profile: str | None = None,
        nacos_properties: NacosProperties | None = None,
    ) -> "BaseConfig":
        """按 profile 加载多环境 YAML 配置（application.yml + application-{profile}.yml + 环境变量 + Nacos）。

        profile 优先级：显式参数 > 环境变量 SPRING_PROFILES_ACTIVE > application.yml 中 spring.profiles.active > dev
        """
        config_dir = Path(config_dir)
        if not config_dir.exists():
            raise FileNotFoundError(f"配置目录不存在: {config_dir}")

        if profile is None:
            profile = os.getenv("SPRING_PROFILES_ACTIVE") or cls._read_profile_from_yaml(config_dir) or "dev"

        merged: dict[str, Any] = {}
        base_file = config_dir / "application.yml"
        profile_file = config_dir / f"application-{profile}.yml"

        if base_file.exists():
            merged = cls._load_yaml(base_file)
        if profile_file.exists():
            merged = cls._deep_merge(merged, cls._load_yaml(profile_file))

        merged = cls._resolve_property_placeholders(merged)
        merged = cls._deep_merge(merged, cls._collect_env_overrides(merged))
        merged = cls._resolve_property_placeholders(merged)

        # Nacos 配置中心合并（远程优先级最高）
        nacos_list = cls._resolve_nacos_properties(nacos_properties, merged)
        for props in nacos_list:
            if os.getenv("SKIP_NACOS_CONFIG", "").lower() in ("1", "true", "yes"):
                break
            try:
                from web_infra.capabilities.config.nacos_config_loader import NacosConfigLoader

                loader = NacosConfigLoader(props)
                loader.load_sync()
                merged = loader.merge(merged)
                merged = cls._resolve_property_placeholders(merged)
            except Exception as e:
                print(f"[Nacos] 配置中心加载失败，使用本地配置继续启动: {e}")

        merged = cls._unflatten_flat_keys(merged)
        return cls(**merged)

    @classmethod
    def _read_profile_from_yaml(cls, config_dir: Path) -> str | None:
        """读取 application.yml 中 spring.profiles.active"""
        base_file = config_dir / "application.yml"
        if not base_file.exists():
            return None
        try:
            data = cls._load_yaml(base_file)
        except Exception:
            return None
        active = data.get("spring", {}).get("profiles", {}).get("active")
        return str(active) if active else None

    @classmethod
    def _resolve_nacos_properties(
        cls, nacos_properties: NacosProperties | None, merged: dict[str, Any]
    ) -> list[NacosProperties]:
        """解析 Nacos 配置中心属性（优先显式传入，其次 spring.config.import）"""
        if nacos_properties and nacos_properties.config_enabled:
            return [nacos_properties]
        imports = merged.get("spring", {}).get("config", {}).get("import", [])
        if isinstance(imports, str):
            imports = [imports]
        nacos_cfg = merged.get("spring", {}).get("cloud", {}).get("nacos", {})
        config_center = nacos_cfg.get("config", {})
        props_list: list[NacosProperties] = []
        for item in imports or []:
            if isinstance(item, str) and item.startswith("nacos:"):
                props_list.append(
                    NacosProperties(
                        server_addresses=nacos_cfg.get("server-addr", "localhost:8848"),
                        namespace=config_center.get("namespace", "public"),
                        group=config_center.get("group", "DEFAULT_GROUP"),
                        data_id=item[len("nacos:"):].strip(),
                        username=nacos_cfg.get("username", ""),
                        password=nacos_cfg.get("password", ""),
                        config_enabled=True,
                    )
                )
        return props_list

    @classmethod
    def _load_yaml(cls, path: Path) -> dict[str, Any]:
        """加载 YAML 文件并解析环境变量占位符"""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return resolve_env_placeholders(data if isinstance(data, dict) else {})

    @classmethod
    def _resolve_property_placeholders(cls, data: Any, properties: dict | None = None) -> Any:
        """递归解析 ${property.name:default} 属性占位符"""
        if properties is None:
            properties = cls._extract_properties(data)
        if isinstance(data, dict):
            return {k: cls._resolve_property_placeholders(v, properties) for k, v in data.items()}
        if isinstance(data, list):
            return [cls._resolve_property_placeholders(item, properties) for item in data]
        if isinstance(data, str):
            return cls._replace_property_placeholders(data, properties)
        return data

    @classmethod
    def _extract_properties(cls, data: Any, prefix: str = "") -> dict[str, Any]:
        """提取配置属性源（点号路径键）"""
        properties: dict[str, Any] = {}
        if isinstance(data, dict):
            for k, v in data.items():
                key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    properties.update(cls._extract_properties(v, key))
                else:
                    properties[key] = v
        return properties

    @staticmethod
    def _replace_property_placeholders(value: str, properties: dict[str, Any]) -> str:
        """替换 ${property.name:default} 属性占位符"""
        pattern = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_.\-]*)(?::([^}]*))?\}")

        def replacer(match: re.Match) -> str:
            prop_name = match.group(1)
            if prop_name in properties:
                return str(properties[prop_name])
            return match.group(2) if match.group(2) is not None else match.group(0)

        return pattern.sub(replacer, value)

    @classmethod
    def _deep_merge(cls, base: dict, override: dict) -> dict:
        """递归合并字典，override 优先级更高，忽略 None 值"""
        result = base.copy()
        for key, value in override.items():
            if value is None:
                continue
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = cls._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @classmethod
    def _unflatten_flat_keys(cls, data: dict[str, Any]) -> dict[str, Any]:
        """将 spring__datasource__url 形式双下划线键转换为嵌套字典"""
        result: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, dict):
                value = cls._unflatten_flat_keys(value)
            if isinstance(key, str) and "__" in key and not key.startswith("_"):
                cls._set_nested(result, key.split("__"), value)
            else:
                result[key] = value
        return result

    @classmethod
    def _collect_env_overrides(cls, config: dict, prefix: str = "SPRING") -> dict:
        """收集 SPRING_* 环境变量覆盖值"""
        overrides: dict[str, Any] = {}
        env_pattern = re.compile(rf"^{prefix}_(.+)$", re.IGNORECASE)
        for key, value in os.environ.items():
            match = env_pattern.match(key)
            if match:
                cls._set_nested(overrides, match.group(1).lower().split("_"), value)
        return overrides

    @classmethod
    def _set_nested(cls, target: dict, path: list[str], value: Any) -> None:
        """按路径设置嵌套字典值"""
        for part in path[:-1]:
            target = target.setdefault(part, {})
        target[path[-1]] = value

    def get(self, key: str, default: Any = None) -> Any:
        """按点号路径获取配置值"""
        keys = key.split(".")
        value: Any = self.model_dump()
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
