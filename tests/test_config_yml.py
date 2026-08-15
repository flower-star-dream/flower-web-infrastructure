"""
YAML 配置与配置驱动中间件单元测试

@Author: 花海
@Date: 2026/08/14 21:00
@Description: 验证配置统一走 YAML（默认源加载 application.default.yml）、dict 入参默认值回落、
              app.web.middlewares 配置驱动中间件装配（enabled 开关/未知中间件报错）、
              多租户/AI 等特殊场景默认不启用。
"""
import pytest

from web_infra import Application, create_app
from web_infra.config import ConfigError, Settings
from web_infra.web import AuthMiddleware, IdempotencyMiddleware, TraceIdMiddleware


def test_default_yml_loaded_by_settings():
    """默认配置源加载 YAML：组件类型/特殊场景默认关闭"""
    source = Settings.default_source()
    assert source.get("app.cache.type") == "memory"
    assert source.get("app.db.type") == "mysql"
    # 特殊场景默认不启用（需业务配置显式开启）
    assert source.get("app.ai.enabled") is False
    assert source.get("app.mongo.enabled") is False
    assert source.get("app.tenant.enabled") is False
    # 中间件清单：trace_id 默认引入，auth/idempotency 默认关闭
    middlewares = source.get("app.web.middlewares")
    assert "trace_id" in middlewares
    assert middlewares["auth"]["enabled"] is False
    assert middlewares["idempotency"]["enabled"] is False


def test_dict_settings_falls_back_to_yml_defaults():
    """dict 入参叠加默认源：未提供的键回落 yml 默认值"""
    application = Application({"app.name": "test-app"})
    assert application.settings.get("app.cache.type") == "memory"  # 回落 yml 默认
    assert application.settings.get("app.db.type") == "mysql"
    assert application.settings.get("app.name") == "test-app"  # dict 优先


def test_default_middlewares_trace_id_only():
    """默认配置：仅引入 trace_id 中间件（auth/idempotency 默认关闭）"""
    app = create_app({"app.name": "test-app"})
    classes = [m.cls for m in app.user_middleware]
    assert TraceIdMiddleware in classes
    assert AuthMiddleware not in classes
    assert IdempotencyMiddleware not in classes


def test_middleware_config_enabled_by_user():
    """用户配置启用 auth：中间件被引入（如何引入由配置决定）"""
    app = create_app(
        {
            "app.web.middlewares": {
                "trace_id": {},
                "auth": {"enabled": True, "whitelist": ["/health", "/metrics"]},
            }
        }
    )
    classes = [m.cls for m in app.user_middleware]
    assert TraceIdMiddleware in classes
    assert AuthMiddleware in classes
    auth = next(m for m in app.user_middleware if m.cls is AuthMiddleware)
    assert auth.kwargs["whitelist"] == ("/health", "/metrics")


def test_middleware_config_disabled():
    """配置中 enabled: false 的中间件不引入"""
    app = create_app(
        {
            "app.web.middlewares": {
                "trace_id": {},
                "idempotency": {"enabled": False, "ttl_seconds": 60},
            }
        }
    )
    classes = [m.cls for m in app.user_middleware]
    assert IdempotencyMiddleware not in classes


def test_middleware_config_idempotency_params():
    """idempotency 中间件参数（ttl_seconds）由配置传入"""
    app = create_app(
        {
            "app.web.middlewares": {
                "trace_id": {},
                "idempotency": {"enabled": True, "ttl_seconds": 60},
            }
        }
    )
    middleware = next(m for m in app.user_middleware if m.cls is IdempotencyMiddleware)
    assert middleware.kwargs["ttl_seconds"] == 60


def test_unknown_middleware_raises():
    """配置了未注册的中间件名：抛 ConfigError（提示用户）"""
    with pytest.raises(ConfigError):
        create_app({"app.web.middlewares": {"ghost": {}}})


def test_ai_and_tenant_disabled_by_default():
    """AI 与多租户特殊场景默认不装配（需配置显式启用）"""
    app = create_app({"app.name": "test-app"})
    assert app.state.components["ai"] is None
    assert "mongo" not in app.state.components
