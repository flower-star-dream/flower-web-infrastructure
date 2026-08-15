"""
缓存 P0 整改单元测试（空值缓存 + TTL 抖动）

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证规范 §8.2 空值缓存（防缓存穿透，TTL ≤ 120s）与 §8.3 热点 Key TTL 抖动（防缓存雪崩）。
              覆盖 MemoryCacheBackend 与 RedisCacheBackend（后者用 fake Redis 客户端，无需真实 Redis）。
"""
import asyncio

import pytest

from web_infra.cache import CacheConfig, MemoryCacheBackend
from web_infra.cache.cache_backend_interface import EMPTY_TTL_LIMIT_SECONDS
from web_infra.db.redis_cache_backend import RedisCacheBackend


# ---------------------------------------------------------------------------
# fake Redis 客户端（记录 set 的 ex、exists/delete 调用，模拟键值存储）
# ---------------------------------------------------------------------------


class _FakeRedisClient:
    """最小 Redis 异步客户端替身：set/get/exists/delete"""

    def __init__(self) -> None:
        self.data: dict[str, tuple[object, int | None]] = {}

    async def set(self, name: str, value: object, ex: int | None = None) -> None:
        self.data[name] = (value, ex)

    async def get(self, name: str) -> object | None:
        item = self.data.get(name)
        return item[0] if item is not None else None

    async def exists(self, name: str) -> int:
        return 1 if name in self.data else 0

    async def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            if name in self.data:
                self.data.pop(name)
                removed += 1
        return removed


class _FakeRedisConfig:
    """替身 RedisConfig：connect 返回 fake 客户端"""

    def __init__(self, client: _FakeRedisClient) -> None:
        self._client = client

    async def connect(self) -> _FakeRedisClient:
        return self._client

    async def close(self) -> None:
        return None

    def update_pool_metrics(self) -> None:
        return None


def _redis_backend(client: _FakeRedisClient | None = None) -> tuple[RedisCacheBackend, _FakeRedisClient]:
    """构造 Redis 缓存后端 + fake 客户端（前缀固定 web:）"""
    client = client or _FakeRedisClient()
    backend = RedisCacheBackend(config=_FakeRedisConfig(client), key_prefix="web:")
    return backend, client


# ---------------------------------------------------------------------------
# 整改 1：空值缓存（S8-1，规范 §8.2）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_empty_value_lifecycle():
    """空值写入后 is_empty 为 True，get 视为未命中，非空值不误判"""
    backend = MemoryCacheBackend()
    await backend.set_empty("missing", ttl=60)
    assert await backend.is_empty("missing") is True
    assert await backend.get("missing") is None
    # 真实值不受空值标记干扰
    await backend.set("present", "v")
    assert await backend.is_empty("present") is False
    assert await backend.get("present") == "v"


@pytest.mark.asyncio
async def test_memory_empty_value_ttl_expiry():
    """空值 TTL 过期后 is_empty 失效返回 False"""
    backend = MemoryCacheBackend(CacheConfig(default_ttl_jitter_seconds=0))
    await backend.set_empty("missing", ttl=1)
    assert await backend.is_empty("missing") is True
    await asyncio.sleep(1.05)
    assert await backend.is_empty("missing") is False


@pytest.mark.asyncio
async def test_memory_empty_value_ttl_capped():
    """空值 TTL 超过上限被钳制到 120s（规范 §8.2：TTL ≤ 120s）"""
    backend = MemoryCacheBackend()
    await backend.set_empty("missing", ttl=9999)
    expire_at = backend._store["missing"][1]
    assert expire_at - backend._now() <= EMPTY_TTL_LIMIT_SECONDS + 0.01


@pytest.mark.asyncio
async def test_memory_delete_clears_empty_marker():
    """删除后空值标记一并失效（不残留空值占位）"""
    backend = MemoryCacheBackend()
    await backend.set_empty("missing", ttl=60)
    await backend.delete("missing")
    assert await backend.is_empty("missing") is False


@pytest.mark.asyncio
async def test_redis_empty_value_lifecycle():
    """Redis 空值占位：set_empty 写入独立 #empty Key，is_empty 为 True，get 未命中"""
    backend, client = _redis_backend()
    await backend.set_empty("missing", ttl=60)
    assert await backend.is_empty("missing") is True
    assert await backend.get("missing") is None
    # 空值 Key 与真实 Key 隔离存储
    assert "web:missing#empty" in client.data
    assert "web:missing" not in client.data


@pytest.mark.asyncio
async def test_redis_empty_value_delete_cleans_both():
    """Redis delete 同步清理真实 Key 与空值占位 Key"""
    backend, client = _redis_backend()
    await backend.set("k", "v", ttl=10)
    await backend.set_empty("k", ttl=30)
    await backend.delete("k")
    assert "web:k" not in client.data
    assert "web:k#empty" not in client.data


@pytest.mark.asyncio
async def test_redis_empty_value_ttl_capped():
    """Redis 空值 TTL 超过上限被钳制到 120s（规范 §8.2）"""
    backend, client = _redis_backend()
    await backend.set_empty("missing", ttl=9999)
    assert client.data["web:missing#empty"][1] == EMPTY_TTL_LIMIT_SECONDS


# ---------------------------------------------------------------------------
# 整改 2：热点 Key TTL 抖动（S8-3，规范 §8.3）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_set_ttl_jitter_applied():
    """内存 set 叠加抖动：实际 TTL 落在 [ttl, ttl+jitter) 区间"""
    backend = MemoryCacheBackend(CacheConfig(default_ttl_jitter_seconds=0))
    await backend.set("k", "v", ttl=10, ttl_jitter_seconds=5)
    expire_at = backend._store["k"][1]
    actual = expire_at - backend._now()
    assert 10 <= actual < 15.01


@pytest.mark.asyncio
async def test_memory_set_ttl_jitter_zero_no_jitter():
    """显式 ttl_jitter_seconds=0 关闭抖动，TTL 精确"""
    backend = MemoryCacheBackend(CacheConfig(default_ttl_jitter_seconds=5))
    await backend.set("k", "v", ttl=10, ttl_jitter_seconds=0)
    expire_at = backend._store["k"][1]
    assert abs((expire_at - backend._now()) - 10) < 0.01


@pytest.mark.asyncio
async def test_memory_set_uses_config_default_jitter():
    """未传 ttl_jitter_seconds 时使用配置默认抖动（CacheConfig.default_ttl_jitter_seconds）"""
    backend = MemoryCacheBackend(CacheConfig(default_ttl_jitter_seconds=5))
    await backend.set("k", "v", ttl=10)
    expire_at = backend._store["k"][1]
    actual = expire_at - backend._now()
    assert 10 <= actual < 15.01


@pytest.mark.asyncio
async def test_redis_set_ttl_jitter_applied():
    """Redis set 叠加抖动：写入 Redis 的 ex 落在 [ttl, ttl+jitter) 区间"""
    backend, client = _redis_backend()
    await backend.set("k", "v", ttl=10, ttl_jitter_seconds=5)
    ex = client.data["web:k"][1]
    assert ex is not None
    assert 10 <= ex < 15


@pytest.mark.asyncio
async def test_redis_set_ttl_jitter_uses_constructor_default():
    """Redis 未传 ttl_jitter_seconds 时使用构造参数默认抖动"""
    client = _FakeRedisClient()
    backend = RedisCacheBackend(
        config=_FakeRedisConfig(client), key_prefix="web:", default_ttl_jitter_seconds=5
    )
    await backend.set("k", "v", ttl=10)
    ex = client.data["web:k"][1]
    assert ex is not None
    assert 10 <= ex < 15


@pytest.mark.asyncio
async def test_redis_set_no_ttl_no_jitter():
    """Redis 无 ttl 时保持不设置过期（ex=None），不受抖动影响"""
    backend, client = _redis_backend()
    await backend.set("k", "v", ttl=None, ttl_jitter_seconds=5)
    assert client.data["web:k"][1] is None
