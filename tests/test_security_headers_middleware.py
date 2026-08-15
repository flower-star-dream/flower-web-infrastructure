"""
安全响应头中间件与 CORS 收紧单元测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证整改 S25-1：
              1) SecurityHeadersMiddleware 启用时注入 CSP / X-Content-Type-Options / X-Frame-Options / Referrer-Policy
                 （直接实例化与配置装配两条路径），默认关闭（向后兼容）不注入，头值可配置覆盖；
              2) CORS 通配源与凭证互斥校验：allow_origins=["*"] + allow_credentials=True 抛 ConfigError，
                 显式白名单 + 凭证合法，默认配置（通配源 + 关闭凭证）合法且读取 Settings（app.web.cors.*）。
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from web_infra import create_app
from web_infra.config import ConfigError, DictConfigSource, Settings
from web_infra.web import SecurityHeadersMiddleware, setup_cors


def _build_app_with_headers() -> FastAPI:
    """构建带安全头中间件的测试应用（直接实例化路径）"""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ok")
    def ok():
        return {"code": "S0000"}

    return app


def test_security_headers_injected_when_middleware_added():
    """直接实例化：安全响应头全部注入"""
    client = TestClient(_build_app_with_headers())
    resp = client.get("/ok")
    assert resp.status_code == 200
    assert resp.headers.get("content-security-policy") == "default-src 'self'"
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "no-referrer"


def test_security_headers_not_injected_by_default():
    """默认配置：不引入安全头中间件（向后兼容，不破坏既有响应头断言）"""
    app = create_app({"app.name": "test-app"})

    @app.get("/ok")
    def ok():
        return {"code": "S0000"}

    client = TestClient(app)
    resp = client.get("/ok")
    assert resp.headers.get("content-security-policy") is None
    assert resp.headers.get("x-frame-options") is None


def test_security_headers_enabled_by_config():
    """配置装配启用：中间件经 _MIDDLEWARE_REGISTRY 注册并注入安全头"""
    app = create_app(
        {
            "app.web.middlewares": {
                "security_headers": {"enabled": True},
                "trace_id": {},
            }
        }
    )

    @app.get("/ok")
    def ok():
        return {"code": "S0000"}

    client = TestClient(app)
    resp = client.get("/ok")
    assert resp.status_code == 200
    assert resp.headers.get("content-security-policy") == "default-src 'self'"
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "no-referrer"


def test_security_headers_custom_values_from_config():
    """配置覆盖：安全头值由配置传入（非默认值）"""
    app = create_app(
        {
            "app.web.middlewares": {
                "security_headers": {
                    "enabled": True,
                    "content_security_policy": "default-src 'none'",
                    "x_frame_options": "SAMEORIGIN",
                },
                "trace_id": {},
            }
        }
    )

    @app.get("/ok")
    def ok():
        return {"code": "S0000"}

    client = TestClient(app)
    resp = client.get("/ok")
    assert resp.headers.get("content-security-policy") == "default-src 'none'"
    assert resp.headers.get("x-frame-options") == "SAMEORIGIN"
    assert resp.headers.get("x-content-type-options") == "nosniff"  # 未配置项回落默认


# ---- CORS 互斥校验（整改 S25-1） ----


def test_cors_wildcard_with_credentials_raises():
    """CORS 互斥：通配源 allow_origins=["*"] + allow_credentials=True 抛 ConfigError"""
    app = FastAPI()
    config = SimpleNamespace(cors__allow_origins=["*"], cors__allow_credentials=True)
    with pytest.raises(ConfigError):
        setup_cors(app, config)


def test_cors_explicit_origins_with_credentials_ok():
    """CORS 白名单：显式来源 + allow_credentials=True 合法并注册中间件"""
    app = FastAPI()
    config = SimpleNamespace(
        cors__allow_origins=["https://a.example.com"],
        cors__allow_credentials=True,
    )
    setup_cors(app, config)
    middleware = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    assert middleware.kwargs["allow_origins"] == ["https://a.example.com"]
    assert middleware.kwargs["allow_credentials"] is True


def test_cors_wildcard_without_credentials_ok():
    """CORS 默认：通配源 + allow_credentials=False 合法并注册中间件"""
    app = FastAPI()
    config = SimpleNamespace(cors__allow_origins=["*"], cors__allow_credentials=False)
    setup_cors(app, config)
    middleware = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    assert middleware.kwargs["allow_origins"] == ["*"]
    assert middleware.kwargs["allow_credentials"] is False


def test_cors_defaults_read_from_settings():
    """CORS 读取 Settings（app.web.cors.*）：默认 yml 为通配源 + 关闭凭证，互斥校验通过"""
    app = FastAPI()
    settings = Settings(Settings.default_source())
    setup_cors(app, settings)
    middleware = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    assert middleware.kwargs["allow_origins"] == ["*"]
    assert middleware.kwargs["allow_credentials"] is False


def test_cors_settings_with_explicit_whitelist_and_credentials():
    """CORS Settings 覆盖：显式白名单 + 凭证开启合法（验证 app.web.cors.* 键读取路径）"""
    app = FastAPI()
    settings = Settings(
        DictConfigSource(
            {
                "app.web.cors.allow_origins": ["https://b.example.com"],
                "app.web.cors.allow_credentials": True,
            }
        )
    )
    setup_cors(app, settings)
    middleware = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    assert middleware.kwargs["allow_origins"] == ["https://b.example.com"]
    assert middleware.kwargs["allow_credentials"] is True
