"""
缓存后端单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证内存缓存后端的 get/set/delete/exists、TTL 与容量淘汰（规范 §8 / §16.5）。
"""
import asyncio

import pytest

from web_infra.cache import CacheConfig, MemoryCacheBackend


@pytest.mark.asyncio
async def test_set_get():
    """写入与读取"""
    backend = MemoryCacheBackend()
    await backend.set("k", "v")
    assert await backend.get("k") == "v"


@pytest.mark.asyncio
async def test_delete_and_exists():
    """删除与存在性判断"""
    backend = MemoryCacheBackend()
    await backend.set("k", "v")
    assert await backend.exists("k") is True
    await backend.delete("k")
    assert await backend.exists("k") is False
    assert await backend.get("k") is None


@pytest.mark.asyncio
async def test_capacity_eviction():
    """超容量淘汰最旧项"""
    backend = MemoryCacheBackend(CacheConfig(max_size=2))
    await backend.set("a", 1)
    await backend.set("b", 2)
    await backend.set("c", 3)
    assert await backend.get("a") is None
    assert await backend.get("b") == 2
    assert await backend.get("c") == 3


@pytest.mark.asyncio
async def test_ttl_expiry():
    """TTL 过期后读取返回 None"""
    # 显式关闭 TTL 抖动（规范 §8.3），确保 1s 过期精确生效
    backend = MemoryCacheBackend(CacheConfig(default_ttl=1, default_ttl_jitter_seconds=0))
    await backend.set("k", "v", ttl=1)
    assert await backend.get("k") == "v"
    await asyncio.sleep(1.05)
    assert await backend.get("k") is None
