"""
应用启动器单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证 Application 配置驱动自动装配（Spring Boot 风格）与统一鉴权上下文注入顺序（规范 §6.4）。
"""
import httpx
import pytest

from web_infra import (
    Application,
    create_app,
    MemoryCacheBackend,
    RedisCacheBackend,
    InMemoryMessageQueue,
    LocalObjectStorage,
    InMemoryServiceRegistry,
    MySQLConfig,
    MySQLConnectionSettings,
    MySQLDatabase,
    SqliteSessionFactory,
)

_SECRET = "test-secret-for-application-0123456789"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    """注入 JWT 测试密钥；测试后清理 JWTUtil 全局注入（cache.type=redis 用例会装配 Redis 配置，避免污染后续用例）"""
    from web_infra.security import JWTUtil

    monkeypatch.setenv("JWT_SECRET_KEY", _SECRET)
    yield
    JWTUtil.configure(None, None)
    JWTUtil.set_redis_config(None)


def test_application_default_components():
    """默认配置装配组件：db 默认 MySQL（懒加载不连接），MongoDB 不装配"""
    app = create_app({"app.name": "test-app"})
    components = app.state.components

    assert isinstance(components["cache"], MemoryCacheBackend)
    assert isinstance(components["mq"], InMemoryMessageQueue)
    assert isinstance(components["storage"], LocalObjectStorage)
    assert isinstance(components["registry"], InMemoryServiceRegistry)
    assert isinstance(components["db"], MySQLDatabase)
    assert "mongo" not in components


def test_application_config_switch_cache_to_redis():
    """配置切换为 Redis 缓存（懒连接，实例化不触发连接）"""
    app = create_app({"app.cache.type": "redis"})
    assert isinstance(app.state.components["cache"], RedisCacheBackend)


def test_application_config_switch_db_to_sqlite():
    """配置切换为 sqlite（轻量参考实现）"""
    app = create_app({"app.db.type": "sqlite"})
    assert isinstance(app.state.components["db"], SqliteSessionFactory)


def test_application_component_accessor():
    """组件访问器 component() 与 app.state 注入一致"""
    app = create_app()
    assert app.state.components["cache"] is app.state.cache
    # Application 实例上的 component 方法也可访问
    application = Application({"app.name": "x"})
    application.build()
    assert application.component("cache") is application.app.state.cache


@pytest.mark.asyncio
async def test_auth_payload_identity_not_overwritten():
    """统一鉴权启用后：业务获取的 user_id 来自 token payload，请求头 X-User-Id 不得覆盖（规范 §6.4）"""
    from web_infra.context import RequestContext
    from web_infra.security import JWTUtil

    app = create_app(
        {
            "app": {
                "name": "test-app",
                "web": {
                    # auth 先声明（内层最后执行注入 payload），trace_id 后声明（外层先执行透传）
                    "middlewares": {
                        "auth": {
                            "enabled": True,
                            "whitelist": ["/health", "/metrics", "/docs", "/redoc", "/openapi.json"],
                        },
                        "trace_id": {},
                    }
                },
            }
        }
    )

    @app.get("/whoami")
    async def whoami():
        return {"user_id": RequestContext.get_user_id()}

    token = await JWTUtil.generate_token(user_id="u1", username="tester", extra_claims={"scope": "read"})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 请求头伪造 X-User-Id，统一鉴权应覆盖为 token payload 身份
        resp = await client.get(
            "/whoami",
            headers={"Authorization": f"Bearer {token}", "X-User-Id": "forged-user"},
        )
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "u1"


@pytest.mark.asyncio
async def test_no_auth_request_header_passthrough():
    """未启用统一鉴权时：请求头 X-User-Id 透传到业务（规范 §6.5 服务调用链）"""
    from web_infra.context import RequestContext

    app = create_app({"app.name": "test-app"})

    @app.get("/whoami")
    async def whoami():
        return {"user_id": RequestContext.get_user_id()}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/whoami", headers={"X-User-Id": "svc-1"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "svc-1"


def test_application_tenant_enabled_installs_filter():
    """多租户启用后：数据库工厂自动装配租户过滤器（多租户规范 §2）"""
    from web_infra.db import TenantQueryFilter

    app = create_app({"app": {"tenant": {"enabled": True, "strict": True}}})
    db = app.state.components["db"]
    assert isinstance(db, MySQLDatabase)
    assert isinstance(db._tenant_filter, TenantQueryFilter)
    assert db._tenant_filter._strict is True


@pytest.mark.asyncio
async def test_tenant_strict_rejects_session_without_context():
    """多租户 strict：无租户上下文创建会话抛 E2-PERM-000（多租户规范 §2 无上下文拒绝执行）"""
    from web_infra.context import RequestContext
    from web_infra.db import TenantQueryFilter
    from web_infra.error import BizException

    db = MySQLDatabase(MySQLConfig(settings=MySQLConnectionSettings(host="localhost")))
    db.install_tenant_filter(TenantQueryFilter(strict=True))

    RequestContext.clear()
    with pytest.raises(BizException):
        await db.create_session()


@pytest.mark.asyncio
async def test_tenant_header_injected_into_context():
    """请求头 X-Tenant-Id 注入租户上下文（多租户扩展 §1.2）"""
    from web_infra.context import RequestContext

    app = create_app({"app.name": "test-app"})

    @app.get("/whoami")
    async def whoami():
        return {"tenant_id": RequestContext.get_tenant_id()}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/whoami", headers={"X-Tenant-Id": "t-1001"})
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == "t-1001"
