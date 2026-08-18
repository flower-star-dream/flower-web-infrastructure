"""
认证与 API 增强整改单元测试（第 7 批，组 1）

@Author: 花海
@Date: 2026/08/15 14:00
@Description: 覆盖 S6-1 凭证即将过期（EXPIRING）/refresh token 签发校验与防混用、
              S6-2 deviceId 同设备凭证复用、S6-3 expires_in 与 exp 一致、S6-4 服务链路头注入与
              剥离 Authorization、S12-2 排序参数结构化、S22-3 签名 URL、S22-4 属主校验钩子、
              S25-2 数据权限守卫（owner_id 越权拦截）、S25-3 SSRF 目标地址校验钩子。
"""
import time

import httpx
import jwt
import pytest
from pydantic import ValidationError

from web_infra.infra.constants import AuthConstant
from web_infra.infra.context import RequestContext
from web_infra.capabilities.db.page_query import PageQuery
from web_infra.infra.error import BizException, PermException
from web_infra.capabilities.http.feign_client import FeignClient, default_url_validator
from web_infra.capabilities.registry import InMemoryServiceRegistry, ServiceInstance
from web_infra.capabilities.security import (
    InMemoryOAuth2ClientRegistry,
    JWTUtil,
    OAuth2Client,
    OAuth2TokenService,
    TokenVerifyStatus,
)
from web_infra.capabilities.security.data_permission import DataPermissionGuard
from web_infra.capabilities.security.secure_config_loader import SecureConfigLoader
from web_infra.capabilities.storage import LocalObjectStorage, StorageConfig


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    """注入 JWT 测试密钥与默认有效期（120 分钟，避免默认用例误触发 EXPIRING 阈值）"""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-auth-enhance-0123456789abcdef")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "120")


# ---------------------------------------------------------------------------
# S6-1：凭证即将过期（EXPIRING）+ refresh token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_short_ttl_returns_expiring():
    """S6-1：剩余有效期低于阈值（REFRESH_THRESHOLD_SECONDS=300）的 token 校验返回 EXPIRING 而非 VALID"""
    token = await JWTUtil.generate_token(user_id="u-exp", username="tester", expires_in=120)
    payload, status = await JWTUtil.verify_token(token)
    assert status == TokenVerifyStatus.EXPIRING
    assert payload is not None
    assert payload["sub"] == "u-exp"


@pytest.mark.asyncio
async def test_verify_normal_token_valid():
    """S6-1：有效期充足的 token（默认 120 分钟）校验返回 VALID，不受 EXPIRING 阈值影响"""
    token = await JWTUtil.generate_token(user_id="u-valid", username="tester")
    _, status = await JWTUtil.verify_token(token)
    assert status == TokenVerifyStatus.VALID


@pytest.mark.asyncio
async def test_token_has_kid_header():
    """S15-3：签发 token（access/refresh）带 kid 密钥版本标识（header），供密钥轮换区分"""
    access = await JWTUtil.generate_token(user_id="u-kid", username="tester")
    assert jwt.get_unverified_header(access).get("kid") == JWTUtil.JWT_KID
    refresh = await JWTUtil.create_refresh_token(user_id="u-kid", username="tester")
    assert jwt.get_unverified_header(refresh).get("kid") == JWTUtil.JWT_KID


@pytest.mark.asyncio
async def test_refresh_token_roundtrip():
    """S6-1：refresh token 签发与校验通过，载荷含 token_type=refresh"""
    refresh = await JWTUtil.create_refresh_token(user_id="u-ref", username="tester")
    payload, status = await JWTUtil.verify_refresh_token(refresh)
    assert status == TokenVerifyStatus.VALID
    assert payload is not None
    assert payload["token_type"] == "refresh"
    assert payload["sub"] == "u-ref"


@pytest.mark.asyncio
async def test_refresh_and_access_not_interchangeable():
    """S6-1：refresh token 与 access token 双向防混用（不同密钥段 + 用途字段双重区分）"""
    access = await JWTUtil.generate_token(user_id="u-mix", username="tester")
    refresh = await JWTUtil.create_refresh_token(user_id="u-mix", username="tester")
    # refresh token 当作 access token 校验：INVALID
    _, status_access = await JWTUtil.verify_token(refresh)
    assert status_access == TokenVerifyStatus.INVALID
    # access token 当作 refresh token 校验：INVALID
    _, status_refresh = await JWTUtil.verify_refresh_token(access)
    assert status_refresh == TokenVerifyStatus.INVALID


@pytest.mark.asyncio
async def test_refresh_token_expired():
    """S6-1：过期 refresh token 校验返回 EXPIRED"""
    now = int(time.time())
    expired = jwt.encode(
        {
            "sub": "u-expired-refresh",
            "iat": now - 200,
            "exp": now - 100,
            "iss": AuthConstant.AUTH_JWT_ISSUER,
            "jti": "x",
            "token_type": "refresh",
        },
        JWTUtil._refresh_secret(),
        algorithm=AuthConstant.AUTH_JWT_ALGORITHM,
    )
    payload, status = await JWTUtil.verify_refresh_token(expired)
    assert payload is None
    assert status == TokenVerifyStatus.EXPIRED


# ---------------------------------------------------------------------------
# S6-2：deviceId 同设备凭证隔离（复用）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_device_token_reuse():
    """S6-2：同 user+client+device 新签发替换旧 jti（复用语义）；不同 device 互不影响；不传按 user_id 聚合"""
    await JWTUtil.generate_token(user_id="u-dev", username="tester", client_id="web", device_id="d1")
    first_jti = JWTUtil.get_current_device_jti("u-dev", "web", "d1")
    token2 = await JWTUtil.generate_token(user_id="u-dev", username="tester", client_id="web", device_id="d1")
    second_jti = JWTUtil.get_current_device_jti("u-dev", "web", "d1")
    # 新签发替换旧 jti：两次 jti 不同，且当前有效 jti 为最新
    assert first_jti != second_jti
    assert JWTUtil.get_current_device_jti("u-dev", "web", "d1") == second_jti
    payload2 = jwt.decode(token2, SecureConfigLoader.get_jwt_secret(), algorithms=[AuthConstant.AUTH_JWT_ALGORITHM])
    assert payload2["jti"] == second_jti
    # 不同 device 各自独立维护
    await JWTUtil.generate_token(user_id="u-dev", username="tester", client_id="web", device_id="d2")
    assert JWTUtil.get_current_device_jti("u-dev", "web", "d2") != JWTUtil.get_current_device_jti("u-dev", "web", "d1")
    # 不传 client/device 时按 user_id 聚合（与旧逻辑兼容）
    await JWTUtil.generate_token(user_id="u-dev", username="tester")
    assert JWTUtil.get_current_device_jti("u-dev") is not None


# ---------------------------------------------------------------------------
# S6-3：expires_in 与 JWT 实际 TTL 一致
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oauth_expires_in_matches_exp():
    """S6-3：OAuth2 返回的 expires_in 与 JWT 实际 exp-iat 一致（声明时效 = 实际签发 TTL）"""
    registry = InMemoryOAuth2ClientRegistry()
    registry.register(OAuth2Client(client_id="svc", client_secret="secret", scopes=("read",)))
    service = OAuth2TokenService(registry)
    response = await service.issue_client_token("svc", "secret")
    assert response["expires_in"] == 15 * 60
    payload = jwt.decode(
        response["access_token"],
        SecureConfigLoader.get_jwt_secret(),
        algorithms=[AuthConstant.AUTH_JWT_ALGORITHM],
    )
    assert abs((payload["exp"] - payload["iat"]) - response["expires_in"]) <= 1


# ---------------------------------------------------------------------------
# S6-4：FeignClient 链路头注入 + 剥离 Authorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feign_injects_service_headers_and_strips_auth():
    """S6-4：FeignClient 自动注入链路头（X-Service-Id/X-User-Id/X-Trace-Id/X-Client-Id）并剥离 Authorization"""
    registry = InMemoryServiceRegistry()
    await registry.register("svc", ServiceInstance(ip="10.1.2.3", port=8080))
    client = FeignClient(registry, retries=1, retry_delay_base=0.0)
    captured: dict = {}

    async def fake_request(method: str, url: str, **kwargs) -> httpx.Response:
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = dict(kwargs.get("headers") or {})
        return httpx.Response(200, request=httpx.Request(method, url))

    client._client.request = fake_request  # type: ignore[method-assign]
    try:
        RequestContext.set_service_id("order-svc")
        RequestContext.set_user_id("u-1")
        RequestContext.set_trace_id("trace-1")
        RequestContext.set_client_id("web")
        resp = await client.get("svc", "/orders", headers={"Authorization": "Bearer user-token", "X-Custom": "v"})
        assert resp is not None
        assert resp.status_code == 200
        headers = captured["headers"]
        assert headers["X-Service-Id"] == "order-svc"
        assert headers["X-User-Id"] == "u-1"
        assert headers["X-Trace-Id"] == "trace-1"
        assert headers["X-Client-Id"] == "web"
        assert headers["X-Custom"] == "v"
        assert "Authorization" not in headers  # 服务间调用禁止裸传用户凭证
        assert captured["url"] == "http://10.1.2.3:8080/orders"
    finally:
        RequestContext.clear()
        await client.close()


@pytest.mark.asyncio
async def test_feign_no_context_no_injection_error():
    """S6-4：无请求上下文时不注入链路头也不抛错（跳过注入，保持向后兼容）"""
    registry = InMemoryServiceRegistry()
    await registry.register("svc", ServiceInstance(ip="10.1.2.3", port=8080))
    client = FeignClient(registry, retries=1, retry_delay_base=0.0)
    captured: dict = {}

    async def fake_request(method: str, url: str, **kwargs) -> httpx.Response:
        captured["headers"] = dict(kwargs.get("headers") or {})
        return httpx.Response(200, request=httpx.Request(method, url))

    client._client.request = fake_request  # type: ignore[method-assign]
    try:
        await client.get("svc", "/orders")
        headers = captured["headers"]
        assert "X-Service-Id" not in headers
        assert "Authorization" not in headers
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# S25-3：SSRF 目标地址校验钩子
# ---------------------------------------------------------------------------


def test_default_url_validator_rejects_private():
    """S25-3：default_url_validator 拒绝本机/内网地址，公网域名放行"""
    for bad in (
        "http://127.0.0.1/x",
        "http://localhost/x",
        "http://10.0.0.8/x",
        "http://192.168.1.1/x",
        "http://172.16.0.1/x",
    ):
        with pytest.raises(ValueError):
            default_url_validator(bad)
    default_url_validator("http://example.com/x")  # 不抛错


@pytest.mark.asyncio
async def test_feign_url_validator_applied():
    """S25-3：注入 url_validator 后请求内网地址被拒绝（校验失败包装为 BizException）"""
    registry = InMemoryServiceRegistry()
    await registry.register("svc", ServiceInstance(ip="127.0.0.1", port=9))
    client = FeignClient(registry, retries=1, retry_delay_base=0.0, url_validator=default_url_validator)
    try:
        with pytest.raises(BizException):
            await client.request("svc", "GET", "/x")
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# S12-2：排序参数结构化
# ---------------------------------------------------------------------------


def test_page_query_order_clause():
    """S12-2：order_clause 返回 (sort, order) 结构化元组；非法 order 抛 ValidationError"""
    assert PageQuery(sort="created_at", order="asc").order_clause() == ("created_at", "asc")
    assert PageQuery(sort="x", order="desc").order_clause() == ("x", "desc")
    assert PageQuery().order_clause() == (None, "asc")
    with pytest.raises(ValidationError):
        PageQuery(sort="x", order="invalid")  # type: ignore[arg-type]  # pyright 静态拦截非法 Literal，此处验证 pydantic 运行时校验


# ---------------------------------------------------------------------------
# S25-2：数据权限守卫（owner_id 水平越权）
# ---------------------------------------------------------------------------


def test_data_permission_guard():
    """S25-2：属主一致通过；属主缺失/越权访问他人数据抛 PermException（E2-PERM-000）"""
    guard = DataPermissionGuard()
    guard.check("u1", "u1", "u1")  # 属主一致，通过
    assert guard.is_owner("u1", "u1") is True
    assert guard.is_owner(None, "u1") is False
    assert guard.is_owner("u2", "u1") is False
    with pytest.raises(PermException) as exc_info:
        guard.check(None, "u1", "u1")  # 数据属主缺失
    assert exc_info.value.code == "E2-PERM-000"
    with pytest.raises(PermException):
        guard.check("u2", "u2", "u1")  # 越权访问他人数据
    with pytest.raises(PermException):
        guard.check("u1", "u2", "u2")  # 数据属主与请求声明不一致


# ---------------------------------------------------------------------------
# S22-3：签名 URL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_storage_presign_url_has_expires(tmp_path):
    """S22-3：本地签名 URL 含 expires 过期时间戳与 signature 签名"""
    storage = LocalObjectStorage(StorageConfig(base_dir=str(tmp_path)))
    url = await storage.presign_url("bucket", "k", expires=60)
    assert url.startswith(str(tmp_path))
    assert "expires=" in url
    assert "signature=" in url
    # 默认过期时长使用 StorageConfig.presign_expires
    default_url = await storage.presign_url("bucket", "k")
    assert "expires=" in default_url


# ---------------------------------------------------------------------------
# S22-4：属主校验钩子（向后兼容）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_storage_owner_params_compatible(tmp_path):
    """S22-4：get/delete 支持 owner 参数（向后兼容）；注入 owner_validator 时执行属主校验，可拦截越权下载"""
    storage = LocalObjectStorage(StorageConfig(base_dir=str(tmp_path)))
    await storage.put("bucket", "k", b"hello")
    # 不传/传 owner 但不注入校验器：行为不变，兼容
    assert await storage.get("bucket", "k") == b"hello"
    assert await storage.get("bucket", "k", owner="u1") == b"hello"

    calls: list[tuple] = []

    def record_validator(object_id: str, owner: str | None, current_user: str | None) -> None:
        """记录校验参数"""
        calls.append((object_id, owner, current_user))

    def deny_validator(object_id: str, owner: str | None, current_user: str | None) -> None:
        """拒绝校验：越权下载拦截"""
        raise PermException("无权限")

    RequestContext.set_user_id("u1")
    try:
        # 属主校验通过并携带 (object_id, owner, current_user)
        assert await storage.get("bucket", "k", owner="u1", owner_validator=record_validator) == b"hello"
        assert calls == [("k", "u1", "u1")]
        # 校验器拒绝时下载被拦截（抛 PermException）
        with pytest.raises(PermException):
            await storage.get("bucket", "k", owner="u2", owner_validator=deny_validator)
        # delete 同样支持 owner 参数与校验钩子
        await storage.delete("bucket", "k", owner="u1")
        assert await storage.exists("bucket", "k") is False
    finally:
        RequestContext.clear()
