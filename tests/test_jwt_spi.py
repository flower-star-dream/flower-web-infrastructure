"""
JWT SPI 单元测试

@Author: 花海
@Date: 2026/08/16 14:00
@Description: 覆盖 JwtTokenStore（内存默认）/ JwtKeyProvider（环境变量默认）行为，
              JWTUtil.configure 注入自定义实现，以及 set_redis_config 的
              "启用 Redis → Redis 状态存储，否则内存" 默认回落与优先级。
"""
import pytest

from web_infra.capabilities.security.env_jwt_key_provider import EnvJwtKeyProvider
from web_infra.capabilities.security.in_memory_jwt_token_store import InMemoryJwtTokenStore
from web_infra.capabilities.security.jwt_util import JWTUtil
from web_infra.capabilities.security.secure_config_loader import SecureConfigLoader
from web_infra.capabilities.security.token_verify_status_enum import TokenVerifyStatus


class _FakeRedis:
    """记录调用的 fake redis 客户端（get/setex/sadd/expire/delete/srem）"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        self.calls.append(("get", key))
        return self.data.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.calls.append(("setex", key, ttl))
        self.data[key] = value

    async def sadd(self, key: str, value: str) -> None:
        self.calls.append(("sadd", key, value))

    async def expire(self, key: str, ttl: int) -> None:
        self.calls.append(("expire", key, ttl))

    async def delete(self, *keys: str) -> int:
        self.calls.append(("delete",) + keys)
        return len(keys)

    async def srem(self, key: str, value: str) -> int:
        self.calls.append(("srem", key, value))
        return 1


class _FakeRedisConfig:
    """返回固定 fake 客户端的 RedisConfig 替身（仅需 connect）"""

    def __init__(self, fake: _FakeRedis) -> None:
        self._fake = fake

    async def connect(self) -> _FakeRedis:
        return self._fake


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    """注入 JWT 测试密钥；测试后清理 JWTUtil 全局注入（自定义 store/Redis 配置），避免污染其他测试文件"""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-jwt-spi-0123456789abcdef")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "120")
    yield
    JWTUtil.configure(None, None)
    JWTUtil.set_redis_config(None)


@pytest.mark.asyncio
async def test_env_key_provider_defaults():
    """EnvJwtKeyProvider：access 密钥取环境变量，refresh 密钥独立段，算法 HS256"""
    provider = EnvJwtKeyProvider()
    assert provider.access_secret() == SecureConfigLoader.get_jwt_secret()
    assert provider.refresh_secret() == SecureConfigLoader.get_jwt_secret() + ":refresh"
    assert provider.algorithm() == "HS256"


@pytest.mark.asyncio
async def test_in_memory_store_roundtrip():
    """InMemoryJwtTokenStore：save 后 exists 通过、revoke 后失效、同设备复用返回旧 jti"""
    store = InMemoryJwtTokenStore()
    assert await store.save("u-1", "jti-1", 120, "web", "d1") is None
    assert await store.exists("u-1", "jti-1") is True
    assert await store.current_jti("u-1", "web", "d1") == "jti-1"
    old = await store.save("u-1", "jti-2", 120, "web", "d1")
    assert old == "jti-1"
    assert await store.current_jti("u-1", "web", "d1") == "jti-2"
    assert await store.exists("u-1", "jti-1") is False
    assert await store.revoke("u-1", "jti-2") is True
    assert await store.exists("u-1", "jti-2") is False
    assert await store.revoke("u-1", "ghost") is False


@pytest.mark.asyncio
async def test_configure_custom_key_provider():
    """JWTUtil.configure：注入自定义密钥提供器后签发/校验使用自定义密钥"""
    custom = "custom-secret-0123456789abcdefghijklmnopqrstuvwxyz"

    class CustomKeyProvider:
        def access_secret(self) -> str:
            return custom

        def refresh_secret(self) -> str:
            return custom + ":refresh"

        def algorithm(self) -> str:
            return "HS256"

    JWTUtil.configure(key_provider=CustomKeyProvider())
    token = await JWTUtil.generate_token(user_id="u-custom", username="tester")
    payload, status = await JWTUtil.verify_token(token)
    assert status == TokenVerifyStatus.VALID
    assert payload["sub"] == "u-custom"


@pytest.mark.asyncio
async def test_configure_custom_token_store():
    """JWTUtil.configure：注入自定义状态存储后 save 走自定义实现"""
    calls: list[str] = []

    class CustomStore:
        async def save(self, user_id, jti, ttl_seconds, client_id, device_id):
            calls.append(f"save:{user_id}:{jti}")
            return None

        async def exists(self, user_id, jti):
            return True

        async def revoke(self, user_id, jti):
            return True

        async def current_jti(self, user_id, client_id, device_id):
            return None

    JWTUtil.configure(token_store=CustomStore())
    await JWTUtil.generate_token(user_id="u-store", username="tester")
    assert any(c.startswith("save:u-store:") for c in calls)


# ---------------------------------------------------------------------------
# 默认回落与优先级：configure 自定义 > set_redis 显式 > 框架 Redis 默认 > 内存
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_redis_config_uses_redis_store():
    """set_redis_config：注入 Redis 配置后，默认状态存储走 Redis（save 落 setex）"""
    fake = _FakeRedis()
    JWTUtil.set_redis_config(_FakeRedisConfig(fake))
    await JWTUtil.generate_token(user_id="u-redis", username="tester")
    assert any(c[0] == "setex" for c in fake.calls)
    assert any(c[0] == "sadd" for c in fake.calls)


@pytest.mark.asyncio
async def test_configure_priority_over_redis():
    """优先级：configure 注入的自定义 store 优先于 set_redis_config 的 Redis 默认"""
    fake = _FakeRedis()
    JWTUtil.set_redis_config(_FakeRedisConfig(fake))
    calls: list[str] = []

    class CustomStore:
        async def save(self, user_id, jti, ttl_seconds, client_id, device_id):
            calls.append("save")
            return None

        async def exists(self, user_id, jti):
            return True

        async def revoke(self, user_id, jti):
            return True

        async def current_jti(self, user_id, client_id, device_id):
            return None

    JWTUtil.configure(token_store=CustomStore())
    await JWTUtil.generate_token(user_id="u-p", username="tester")
    assert calls == ["save"]
    assert fake.calls == []  # 自定义优先，未走 Redis


@pytest.mark.asyncio
async def test_no_redis_falls_back_memory():
    """未启用 Redis（set_redis_config None）：回落内存实现，同设备凭证复用可查"""
    JWTUtil.set_redis_config(None)
    JWTUtil.configure(None, None)
    await JWTUtil.generate_token(user_id="u-mem", username="tester", client_id="web", device_id="d1")
    assert JWTUtil.get_current_device_jti("u-mem", "web", "d1") is not None


@pytest.mark.asyncio
async def test_get_current_device_jti_async_matches_sync():
    """异步查询入口：get_current_device_jti_async 与同步兼容入口结果一致（H3 修复）"""
    JWTUtil.set_redis_config(None)
    JWTUtil.configure(None, None)
    await JWTUtil.generate_token(user_id="u-async", username="tester", client_id="web", device_id="d1")
    sync_jti = JWTUtil.get_current_device_jti("u-async", "web", "d1")
    async_jti = await JWTUtil.get_current_device_jti_async("u-async", "web", "d1")
    assert async_jti is not None
    assert async_jti == sync_jti
    assert await JWTUtil.get_current_device_jti_async("u-async", "web", "no-such-device") is None


@pytest.mark.asyncio
async def test_in_memory_store_prunes_expired_entries():
    """InMemoryJwtTokenStore：过期条目惰性清理，不残留内存（M5 修复）"""
    store = InMemoryJwtTokenStore()
    await store.save("u-exp", "jti-old", 0, "web", "d1")  # ttl=0 立即过期
    assert await store.exists("u-exp", "jti-old") is False
    assert "u-exp:jti-old" not in store._states
    assert store._user_jtis.get("u-exp") is None  # 集合同步回收
    # save 触发 prune：旧过期条目被清理，仅保留有效凭证
    await store.save("u-exp", "jti-new", 120, "web", "d1")
    assert "u-exp:jti-old" not in store._states
    assert store._user_jtis.get("u-exp") == {"jti-new"}
    # device_map 指向已过期 jti 的条目同步清理
    assert store._device_map.get(("u-exp", "web", "d1")) == "jti-new"
