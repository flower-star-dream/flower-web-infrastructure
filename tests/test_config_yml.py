"""
YAML 配置与配置驱动中间件单元测试

@Author: 花海
@Date: 2026/08/14 21:00
@Description: 验证配置统一走 YAML（默认源加载 application.default.yml）、dict 入参默认值回落、
              app.web.middlewares 配置驱动中间件装配（enabled 开关/未知中间件报错）、
              多租户/AI 等特殊场景默认不启用，以及 YAML 中 ${ENV:default} 环境变量占位符解析。
"""
import pytest

from web_infra import Application, create_app
from web_infra.config import ConfigError, Settings, YamlConfigSource
from web_infra.web import AuthMiddleware, IdempotencyMiddleware, InMemoryIdempotencyStore, RedisIdempotencyStore, TraceIdMiddleware


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


def test_middleware_idempotency_default_memory_store():
    """idempotency 未配 store_type 时默认 memory store（单实例）"""
    app = create_app(
        {
            "app.web.middlewares": {
                "trace_id": {},
                "idempotency": {"enabled": True},
            }
        }
    )
    middleware = next(m for m in app.user_middleware if m.cls is IdempotencyMiddleware)
    assert isinstance(middleware.kwargs["store"], InMemoryIdempotencyStore)


def test_middleware_idempotency_redis_store_reuses_cache():
    """store_type=redis：复用已装配 cache 组件的同一 Redis 客户端（跨实例原子，规范 §12.6）"""
    app = create_app(
        {
            "app.web.middlewares": {
                "trace_id": {},
                "idempotency": {"enabled": True, "store_type": "redis"},
            },
            "app.cache.type": "redis",
        }
    )
    middleware = next(m for m in app.user_middleware if m.cls is IdempotencyMiddleware)
    store = middleware.kwargs["store"]
    assert isinstance(store, RedisIdempotencyStore)
    assert store._redis is app.state.cache.config.client()  # 复用 cache 组件同一客户端实例


def test_middleware_idempotency_redis_without_cache_raises():
    """store_type=redis 但 cache 组件非 Redis：启动期快速失败（ConfigError，明确错误提示）"""
    with pytest.raises(ConfigError):
        create_app(
            {
                "app.web.middlewares": {
                    "trace_id": {},
                    "idempotency": {"enabled": True, "store_type": "redis"},
                },
                "app.cache.type": "memory",
            }
        )


def test_unknown_middleware_raises():
    """配置了未注册的中间件名：抛 ConfigError（提示用户）"""
    with pytest.raises(ConfigError):
        create_app({"app.web.middlewares": {"ghost": {}}})


def test_ai_and_tenant_disabled_by_default():
    """AI 与多租户特殊场景默认不装配（需配置显式启用）"""
    app = create_app({"app.name": "test-app"})
    assert app.state.components["ai"] is None
    assert "mongo" not in app.state.components


def test_yaml_source_env_placeholder(tmp_path, monkeypatch):
    """YAML 配置源解析 ${ENV} / ${ENV:default} 占位符：已定义取环境变量、未定义取默认值、均无则保留原样"""
    monkeypatch.setenv("TEST_DB_PASSWORD", "s3cr3t")
    yml = tmp_path / "app.yml"
    yml.write_text(
        "db:\n"
        "  password: ${TEST_DB_PASSWORD}\n"
        "  host: ${TEST_DB_HOST:127.0.0.1}\n"
        "  name: ${TEST_DB_UNDEFINED}\n",
        encoding="utf-8",
    )
    source = YamlConfigSource(yml)
    assert source.get("db.password") == "s3cr3t"          # 环境变量已定义 -> 取值
    assert source.get("db.host") == "127.0.0.1"           # 未定义 -> 默认值
    assert source.get("db.name") == "${TEST_DB_UNDEFINED}"  # 未定义且无默认值 -> 保留原样


def test_application_yml_env_placeholder_default(tmp_path, monkeypatch):
    """业务 application.yml 经 Settings 链路支持 ${ENV:default}：敏感配置默认值回落（不落盘明文）"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APP_DB_MYSQL_PASSWORD", raising=False)
    (tmp_path / "application.yml").write_text(
        "app:\n  db:\n    mysql:\n      password: ${APP_DB_MYSQL_PASSWORD:pwd123}\n",
        encoding="utf-8",
    )
    source = Settings.default_source()
    assert source.get("app.db.mysql.password") == "pwd123"


def test_application_yml_env_placeholder_overridden_by_env(tmp_path, monkeypatch):
    """环境变量优先于 yml 占位符：即使 yml 写死 ${ENV:default}，显式环境变量仍最高优先级"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_DB_MYSQL_PASSWORD", "s3cr3t")
    (tmp_path / "application.yml").write_text(
        "app:\n  db:\n    mysql:\n      password: ${APP_DB_MYSQL_PASSWORD:pwd123}\n",
        encoding="utf-8",
    )
    source = Settings.default_source()
    assert source.get("app.db.mysql.password") == "s3cr3t"


def test_env_file_loaded_by_settings(tmp_path, monkeypatch):
    """Settings 自动加载项目根 .env：yml ${ENV} 取到 .env 中的敏感值（明文不落盘）"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APP_DB_MYSQL_PASSWORD", raising=False)
    (tmp_path / ".env").write_text("APP_DB_MYSQL_PASSWORD=s3cr3t\n", encoding="utf-8")
    (tmp_path / "application.yml").write_text(
        "app:\n  db:\n    mysql:\n      password: ${APP_DB_MYSQL_PASSWORD:pwd123}\n",
        encoding="utf-8",
    )
    source = Settings.default_source()
    assert source.get("app.db.mysql.password") == "s3cr3t"


def test_env_file_does_not_override_existing_env(tmp_path, monkeypatch):
    """进程环境变量优先于 .env：.env 不覆盖已存在的变量（override=False）"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_DB_MYSQL_PASSWORD", "from_process")
    (tmp_path / ".env").write_text("APP_DB_MYSQL_PASSWORD=from_dotenv\n", encoding="utf-8")
    (tmp_path / "application.yml").write_text(
        "app:\n  db:\n    mysql:\n      password: ${APP_DB_MYSQL_PASSWORD:pwd123}\n",
        encoding="utf-8",
    )
    source = Settings.default_source()
    assert source.get("app.db.mysql.password") == "from_process"
