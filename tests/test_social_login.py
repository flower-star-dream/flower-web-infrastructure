"""
三方登录能力单元测试

@Author: 花海
@Date: 2026/08/16 14:00
@Description: 覆盖三方登录错误码、平台注册表、默认实现（Demo/绑定存储）、
              SocialLoginService 编排（登录/绑定/解绑），全 Mock 不触网。
"""
import pytest

from datetime import datetime, timezone

from web_infra.error import BizException, CommonErrorCode, CommonErrorCodeEnum
from web_infra.security import JWTUtil, TokenVerifyStatus
from web_infra.security.social import (
    DemoSocialPlatform,
    InMemorySocialBindingStore,
    SocialBinding,
    SocialLoginService,
    SocialPlatformRegistry,
)


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    """注入 JWT 测试密钥（登录签发自有 JWT 依赖）"""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-social-login-0123456789abcdef")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "120")


def test_social_error_codes_registered():
    """E2-AUTH-005~008：枚举成员 + CommonErrorCode 属性引用均已注册"""
    assert CommonErrorCodeEnum.AUTH_SOCIAL_PLATFORM_NOT_CONFIGURED.value.code == "E2-AUTH-005"
    assert CommonErrorCodeEnum.AUTH_SOCIAL_TOKEN_FAILED.value.code == "E2-AUTH-006"
    assert CommonErrorCodeEnum.AUTH_SOCIAL_NOT_BOUND.value.code == "E2-AUTH-007"
    assert CommonErrorCodeEnum.AUTH_SOCIAL_ALREADY_BOUND.value.code == "E2-AUTH-008"
    assert CommonErrorCode.AUTH_SOCIAL_PLATFORM_NOT_CONFIGURED.code == "E2-AUTH-005"
    assert CommonErrorCode.AUTH_SOCIAL_TOKEN_FAILED.code == "E2-AUTH-006"
    assert CommonErrorCode.AUTH_SOCIAL_NOT_BOUND.code == "E2-AUTH-007"
    assert CommonErrorCode.AUTH_SOCIAL_ALREADY_BOUND.code == "E2-AUTH-008"
    assert CommonErrorCode.AUTH_SOCIAL_ALREADY_BOUND.http_status == 409


def test_platform_registry_register_get():
    """平台注册表：register 后 get 命中、providers 列出"""
    registry = SocialPlatformRegistry()
    registry.register(DemoSocialPlatform())
    assert registry.get("demo") is not None
    assert registry.get("ghost") is None
    assert registry.providers() == ["demo"]


@pytest.mark.asyncio
async def test_binding_store_roundtrip():
    """内存绑定存储：bind/find/unbind 往返 + 重复绑定冲突（COMMON_CONFLICT）"""
    store = InMemorySocialBindingStore()
    binding = SocialBinding(provider="demo", openid="openid-1", user_id="u-1", bound_at=datetime.now(timezone.utc))
    await store.bind(binding)
    assert await store.find_by_platform("demo", "openid-1") == binding
    assert [b.user_id for b in await store.find_all_by_user_id("u-1")] == ["u-1"]
    with pytest.raises(BizException) as exc:
        await store.bind(binding)
    assert exc.value.code == "E4-COMMON-001"
    assert await store.unbind("demo", "openid-1") is True
    assert await store.find_by_platform("demo", "openid-1") is None
    assert await store.unbind("demo", "openid-1") is False


@pytest.mark.asyncio
async def test_demo_platform_flow():
    """Demo 平台：跳转 URL 含 code、任意 demo- code 换 token、拉取 userinfo 派生 openid"""
    platform = DemoSocialPlatform()
    url = await platform.build_authorize_url("st-1", "https://cb.example.com/cb")
    assert "code=demo-st-1" in url
    token = await platform.exchange_token("demo-st-1", "https://cb.example.com/cb")
    assert token.access_token
    info = await platform.fetch_userinfo(token)
    assert info.provider == "demo"
    assert info.openid == "demo-openid-demo-st-1"


@pytest.mark.asyncio
async def test_demo_platform_invalid_code():
    """Demo 平台：非法授权码抛 E2-AUTH-006"""
    platform = DemoSocialPlatform()
    with pytest.raises(BizException) as exc:
        await platform.exchange_token("bad-code", "https://cb.example.com/cb")
    assert exc.value.code == "E2-AUTH-006"


def _setup_service() -> tuple[SocialLoginService, SocialPlatformRegistry, InMemorySocialBindingStore]:
    """装配：Demo 平台 + 内存绑定存储"""
    registry = SocialPlatformRegistry()
    registry.register(DemoSocialPlatform())
    binding_store = InMemorySocialBindingStore()
    return SocialLoginService(registry, binding_store), registry, binding_store


@pytest.mark.asyncio
async def test_login_bound_issues_jwt():
    """登录：已绑定用户签发自有 JWT，sub 为本地 user_id"""
    service, _, binding_store = _setup_service()
    await binding_store.bind(SocialBinding("demo", "demo-openid-demo-st-9", "u-local", datetime.now(timezone.utc)))
    result = await service.login("demo", "demo-st-9", "https://cb.example.com/cb")
    assert result.bound is True
    assert result.user_id == "u-local"
    payload, status = await JWTUtil.verify_token(result.access_token)
    assert status == TokenVerifyStatus.VALID
    assert payload["sub"] == "u-local"


@pytest.mark.asyncio
async def test_login_unbound_returns_signal():
    """登录：未绑定返回待绑定信号（bound=False），require_bound=True 时抛 E2-AUTH-007"""
    service, _, _ = _setup_service()
    result = await service.login("demo", "demo-st-1", "https://cb.example.com/cb")
    assert result.bound is False
    assert result.access_token is None
    assert result.user_info is not None
    assert result.user_info.openid == "demo-openid-demo-st-1"
    with pytest.raises(BizException) as exc:
        await service.login("demo", "demo-st-1", "https://cb.example.com/cb", require_bound=True)
    assert exc.value.code == "E2-AUTH-007"


@pytest.mark.asyncio
async def test_login_unknown_platform():
    """登录：平台未注册抛 E2-AUTH-005"""
    service, _, _ = _setup_service()
    with pytest.raises(BizException) as exc:
        await service.login("ghost", "demo-st-1", "https://cb.example.com/cb")
    assert exc.value.code == "E2-AUTH-005"


@pytest.mark.asyncio
async def test_bind_binds_and_conflicts():
    """绑定：新绑定落库；已被其他用户绑定抛 E2-AUTH-008；同用户重复绑定幂等"""
    service, _, binding_store = _setup_service()
    binding = await service.bind("demo", "demo-st-2", "https://cb.example.com/cb", "u-2")
    assert binding.user_id == "u-2"
    assert await binding_store.find_by_platform("demo", "demo-openid-demo-st-2") == binding
    again = await service.bind("demo", "demo-st-2", "https://cb.example.com/cb", "u-2")
    assert again == binding
    with pytest.raises(BizException) as exc:
        await service.bind("demo", "demo-st-2", "https://cb.example.com/cb", "u-3")
    assert exc.value.code == "E2-AUTH-008"


@pytest.mark.asyncio
async def test_unbind_owner_check():
    """解绑：非属主抛 PERM_DENIED；属主解绑成功"""
    service, _, binding_store = _setup_service()
    await binding_store.bind(SocialBinding("demo", "openid-x", "u-1", datetime.now(timezone.utc)))
    with pytest.raises(BizException) as exc:
        await service.unbind("demo", "openid-x", "u-2")
    assert exc.value.code == "E2-PERM-000"
    assert await service.unbind("demo", "openid-x", "u-1") is True


@pytest.mark.asyncio
async def test_bind_race_conflict_idempotent_fallback():
    """绑定竞态：检查与落库间另一请求已先行绑定时，服务层捕获冲突幂等返回（M3 修复）"""
    registry = SocialPlatformRegistry()
    registry.register(DemoSocialPlatform())
    existing = SocialBinding("demo", "demo-openid-demo-st-5", "u-5", datetime.now(timezone.utc))

    class RacingStore(InMemorySocialBindingStore):
        """模拟竞态窗口：首次 find 未发现（窗口），bind 抛冲突，冲突后重查返回既有绑定"""

        def __init__(self, raced: SocialBinding) -> None:
            super().__init__()
            self._raced = raced
            self._calls = 0

        async def find_by_platform(self, provider, openid):
            self._calls += 1
            return None if self._calls == 1 else self._raced

        async def bind(self, binding) -> None:
            raise CommonErrorCode.COMMON_CONFLICT.to_exception(message="三方账号已绑定")

    service = SocialLoginService(registry, RacingStore(existing))
    result = await service.bind("demo", "demo-st-5", "https://cb.example.com/cb", "u-5")
    assert result == existing  # 幂等返回既有绑定，不抛 500
    # 属主不同：冲突后重查发现被他人绑定 → E2-AUTH-008
    other = SocialBinding("demo", "demo-openid-demo-st-6", "u-6", datetime.now(timezone.utc))
    service2 = SocialLoginService(registry, RacingStore(other))
    with pytest.raises(BizException) as exc:
        await service2.bind("demo", "demo-st-6", "https://cb.example.com/cb", "u-other")
    assert exc.value.code == "E2-AUTH-008"