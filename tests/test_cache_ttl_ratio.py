"""
本地缓存 TTL 比例约束单元测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证规范 §8.3：本地缓存 TTL 不得超过分布式缓存 TTL 的 1/3（remote_default_ttl *
              local_ttl_ratio_limit）。覆盖超限钳制、未超限正常、remote_default_ttl<=0 跳过钳制、
              set_empty 不受比例约束以及钳制 warning 日志输出。
"""
import asyncio
import logging

import pytest

from web_infra.cache import CacheConfig, MemoryCacheBackend


@pytest.mark.asyncio
async def test_ttl_exceed_limit_clamped():
    """TTL 超过分布式 TTL 的 1/3 时被钳制，未到原 TTL 即过期"""
    backend = MemoryCacheBackend(CacheConfig(remote_default_ttl=6, default_ttl_jitter_seconds=0))
    # 上限 = 6 * 1/3 = 2s；传入 ttl=10 应被钳制为 2s
    await backend.set("k", "v", ttl=10)
    assert await backend.get("k") == "v"
    expire_at = backend._store["k"][1]
    actual_ttl = expire_at - backend._now()
    assert 0 < actual_ttl <= 2.05
    # 2.05s 后原 10s 远未到期，但钳制后的 2s 已过期
    await asyncio.sleep(2.05)
    assert await backend.get("k") is None


@pytest.mark.asyncio
async def test_ttl_within_limit_not_clamped():
    """TTL 未超限时不钳制，按原 TTL 生效"""
    backend = MemoryCacheBackend(CacheConfig(remote_default_ttl=6, default_ttl_jitter_seconds=0))
    await backend.set("k", "v", ttl=1)  # 1 < 2，不钳制
    assert await backend.get("k") == "v"
    expire_at = backend._store["k"][1]
    assert abs((expire_at - backend._now()) - 1.0) < 0.1


@pytest.mark.asyncio
async def test_remote_default_ttl_zero_skips_clamp():
    """remote_default_ttl=0 时跳过钳制（避免除零/负上限），TTL 原样生效"""
    backend = MemoryCacheBackend(CacheConfig(remote_default_ttl=0, default_ttl_jitter_seconds=0))
    await backend.set("k", "v", ttl=10)
    assert await backend.get("k") == "v"
    expire_at = backend._store["k"][1]
    assert abs((expire_at - backend._now()) - 10.0) < 0.1


@pytest.mark.asyncio
async def test_default_ttl_also_clamped():
    """未显式传 ttl 时使用 default_ttl，超限同样被钳制"""
    backend = MemoryCacheBackend(
        CacheConfig(default_ttl=10, remote_default_ttl=6, default_ttl_jitter_seconds=0)
    )
    # 上限 = 2s；default_ttl=10 超限应被钳制为 2s
    await backend.set("k", "v")
    assert await backend.get("k") == "v"
    expire_at = backend._store["k"][1]
    assert 0 < expire_at - backend._now() <= 2.05


@pytest.mark.asyncio
async def test_set_empty_not_subject_to_ratio_clamp():
    """set_empty 不受本地 TTL 1/3 比例钳制约束（上限由 EMPTY_TTL_LIMIT_SECONDS 控制）"""
    backend = MemoryCacheBackend(CacheConfig(remote_default_ttl=3, default_ttl_jitter_seconds=0))
    # 比例上限 = 1s；空值缓存 ttl=10 应按原值生效，而非被钳制为 1s
    await backend.set_empty("missing", ttl=10)
    assert await backend.is_empty("missing") is True
    expire_at = backend._store["missing"][1]
    assert abs((expire_at - backend._now()) - 10.0) < 0.1


@pytest.mark.asyncio
async def test_clamp_logs_warning(caplog):
    """钳制发生时输出 warning 日志（含 key 与实际 ttl，规范 §17 统一日志）"""
    backend = MemoryCacheBackend(CacheConfig(remote_default_ttl=6, default_ttl_jitter_seconds=0))
    with caplog.at_level(logging.WARNING, logger="web_infra"):
        await backend.set("k", "v", ttl=10)
    assert any("k" in record.message and "钳制" in record.message for record in caplog.records)
