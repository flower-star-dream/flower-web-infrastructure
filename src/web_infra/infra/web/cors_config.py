"""
CORS 跨域配置

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一 CORS 跨域配置，从配置对象读取并应用到 FastAPI 应用。
              整改 S25-1：通配源与凭证互斥——allow_origins=["*"] 时 allow_credentials 必须为 false
              （浏览器规范禁止带凭证的通配跨域），显式白名单时可开启；默认值收敛于
              config/application.default.yml（app.web.cors，默认通配源 + 关闭凭证）。
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from web_infra.infra.config import ConfigError, Settings

# CORS 默认值（与 application.default.yml 的 app.web.cors 保持一致）
_DEFAULT_ORIGINS = ["*"]
_DEFAULT_CREDENTIALS = False
_DEFAULT_METHODS = ["*"]
_DEFAULT_HEADERS = ["*"]


def _read_cors_config(config: Any) -> tuple[list[str], bool, list[str], list[str]]:
    """从配置对象读取 CORS 参数（支持 Settings / pydantic 模型 / 属性对象三种形态）。

    :param config: 配置对象——Settings（app.web.cors.* 键）优先；
                   pydantic 模型（model_dump 的 cors__allow_origins 等）次之；属性对象兜底
    :return: (allow_origins, allow_credentials, allow_methods, allow_headers)
    """
    if isinstance(config, Settings):
        origins = config.get("app.web.cors.allow_origins", _DEFAULT_ORIGINS)
        credentials = config.get_bool("app.web.cors.allow_credentials", _DEFAULT_CREDENTIALS)
        methods = config.get("app.web.cors.allow_methods", _DEFAULT_METHODS)
        headers = config.get("app.web.cors.allow_headers", _DEFAULT_HEADERS)
    elif hasattr(config, "model_dump"):
        data = config.model_dump()
        origins = data.get("cors__allow_origins", _DEFAULT_ORIGINS)
        credentials = data.get("cors__allow_credentials", _DEFAULT_CREDENTIALS)
        methods = data.get("cors__allow_methods", _DEFAULT_METHODS)
        headers = data.get("cors__allow_headers", _DEFAULT_HEADERS)
    else:
        origins = getattr(config, "cors__allow_origins", _DEFAULT_ORIGINS)
        credentials = getattr(config, "cors__allow_credentials", _DEFAULT_CREDENTIALS)
        methods = getattr(config, "cors__allow_methods", _DEFAULT_METHODS)
        headers = getattr(config, "cors__allow_headers", _DEFAULT_HEADERS)
    return origins, credentials, methods, headers


def _as_list(value: Any) -> list[str]:
    """归一化为字符串列表（单值包裹为列表）"""
    return value if isinstance(value, list) else [value]


def setup_cors(app: FastAPI, config: Any) -> None:
    """从配置对象读取 CORS 配置并注册到 FastAPI 应用

    :param app: FastAPI 应用实例
    :param config: 配置对象——Settings（app.web.cors.*）或支持 cors__allow_origins 属性/model_dump 的对象
    :raises ConfigError: 通配源 allow_origins=["*"] 与 allow_credentials=True 互斥（整改 S25-1）
    """
    origins, credentials, methods, headers = _read_cors_config(config)
    origins_list = _as_list(origins)
    credentials_bool = bool(credentials)

    if "*" in origins_list and credentials_bool:
        raise ConfigError(
            "CORS 配置非法：allow_origins=['*'] 与 allow_credentials=True 互斥"
            "（浏览器规范禁止带凭证的通配跨域），请改为显式来源白名单或关闭凭证",
            key="app.web.cors",
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins_list,
        allow_credentials=credentials_bool,
        allow_methods=_as_list(methods),
        allow_headers=_as_list(headers),
    )
