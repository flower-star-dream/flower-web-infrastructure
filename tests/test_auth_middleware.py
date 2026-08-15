"""
统一鉴权中间件 + RBAC 权限守卫单元测试

@Author: 花海
@Date: 2026/08/14 20:00
@Description: 验证统一入口鉴权（白名单/缺凭证/非法凭证/过期凭证/上下文注入）与
              接口级权限（PermissionGuard：E2-PERM-000、admin 通配，规范 §6.4/§6.6/§25.3）。
"""
import time

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI

from web_infra.constants import AuthConstant
from web_infra.context import RequestContext
from web_infra.security import JWTUtil, PermissionGuard
from web_infra.security.secure_config_loader import SecureConfigLoader
from web_infra.web import AuthMiddleware

_SECRET = "test-secret-for-auth-middleware-0123456789"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    """注入 JWT 测试密钥"""
    monkeypatch.setenv("JWT_SECRET_KEY", _SECRET)


def _build_app(with_permission: bool = False) -> FastAPI:
    """构造带鉴权中间件的测试应用（可选权限点路由；注册全局异常处理与生产一致）"""
    from web_infra.error import register_global_exception_handlers

    app = FastAPI()
    register_global_exception_handlers(app)
    app.add_middleware(AuthMiddleware)

    @app.get("/secure")
    async def secure():
        return {"user_id": RequestContext.get_user_id()}

    @app.post("/orders")
    async def create_order():
        return {"created": True}

    if with_permission:

        @app.get("/admin-orders", dependencies=[Depends(PermissionGuard.require(AuthConstant.AUTH_PERM_ORDER_WRITE))])
        async def admin_orders():
            return {"admin": True}

        @app.get("/admin-everything", dependencies=[Depends(PermissionGuard.require("NOT_GRANTED"))])
        async def admin_everything():
            return {"admin": True}

    return app


async def _token(user_id: str = "u1", scopes: str = "read write", expires_in: int | None = None) -> str:
    """签发测试 token（expires_in 为 None 时正常有效期）"""
    return await JWTUtil.generate_token(user_id=user_id, username="tester", extra_claims={"scope": scopes})


@pytest.mark.asyncio
async def test_whitelist_path_anonymous_allowed():
    """白名单路径匿名放行"""
    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 404  # 白名单放行进入路由（未注册则 404 而非 401）


@pytest.mark.asyncio
async def test_missing_token_returns_401():
    """受保护路径无凭证：401 E2-AUTH-000"""
    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/secure")
        assert response.status_code == 401
        assert response.json()["code"] == "E2-AUTH-000"


@pytest.mark.asyncio
async def test_valid_token_injects_context():
    """有效凭证：请求上下文注入 user_id"""
    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    token = await _token(user_id="u1", scopes="read")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/secure", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["user_id"] == "u1"


@pytest.mark.asyncio
async def test_invalid_token_returns_401():
    """非法凭证：401 E2-AUTH-002"""
    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/secure", headers={"Authorization": "Bearer not-a-jwt"})
        assert response.status_code == 401
        assert response.json()["code"] == "E2-AUTH-002"


@pytest.mark.asyncio
async def test_expired_token_returns_401():
    """过期凭证：401 E2-AUTH-001"""
    app = _build_app()
    transport = httpx.ASGITransport(app=app)
    expired = jwt.encode(
        {"sub": "u1", "exp": int(time.time()) - 100, "iss": AuthConstant.AUTH_JWT_ISSUER, "jti": "x"},
        SecureConfigLoader.get_jwt_secret(),
        algorithm=AuthConstant.AUTH_JWT_ALGORITHM,
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/secure", headers={"Authorization": f"Bearer {expired}"})
        assert response.status_code == 401
        assert response.json()["code"] == "E2-AUTH-001"


@pytest.mark.asyncio
async def test_permission_granted_passes():
    """具备权限点：放行"""
    app = _build_app(with_permission=True)
    transport = httpx.ASGITransport(app=app)
    token = await _token(user_id="u1", scopes="read write ORDER_WRITE")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin-orders", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_permission_missing_returns_403():
    """缺少权限点：403 E2-PERM-000（规范 §6.6 权限校验失败统一 E2-PERM-000）"""
    app = _build_app(with_permission=True)
    transport = httpx.ASGITransport(app=app)
    token = await _token(user_id="u1", scopes="read")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin-orders", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403
        assert response.json()["code"] == "E2-PERM-000"


@pytest.mark.asyncio
async def test_permission_admin_wildcard():
    """admin 通配所有权限点（§6.6）"""
    app = _build_app(with_permission=True)
    transport = httpx.ASGITransport(app=app)
    token = await _token(user_id="root", scopes="admin")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin-everything", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
