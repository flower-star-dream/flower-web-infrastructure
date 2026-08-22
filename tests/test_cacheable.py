"""
声明式缓存 @cacheable / @cache_evict 单元测试

@Author: 花海
@Date: 2026/08/22 16:00
@Description: 验证普通装饰器形态（不参与 order 排序）：@cacheable 命中缓存不回源、未命中回源并写缓存；
              @cache_evict 调用后删除缓存。基于 CacheBackendInterface（内存后端，无外部依赖）。
"""
import pytest

from web_infra.capabilities.cache import MemoryCacheBackend, CacheConfig
from web_infra.capabilities.cache.cacheable import cacheable, cache_evict
from web_infra.core.aop import bind_components


@pytest.fixture()
def mem_cache():
    backend = MemoryCacheBackend(CacheConfig())
    bind_components({"cache": backend})
    return backend


@pytest.mark.asyncio
async def test_cacheable_hits_cache_skips_source(mem_cache):
    """命中缓存：不回源（源函数不被调用）"""
    calls = []

    @cacheable("order:{0}")
    async def get_order(oid):
        calls.append(oid)
        return f"order-{oid}"

    r1 = await get_order(1)
    r2 = await get_order(1)
    assert r1 == "order-1" and r2 == "order-1"
    assert calls == [1]  # 第二次命中缓存，不回源


@pytest.mark.asyncio
async def test_cacheable_miss_writes_cache(mem_cache):
    """未命中：回源并把结果写入缓存"""

    @cacheable("order:{0}")
    async def get_order(oid):
        return f"order-{oid}"

    await get_order(2)
    key = "order:2"
    assert await mem_cache.exists(key) is True


@pytest.mark.asyncio
async def test_cache_evict_deletes_cache(mem_cache):
    """@cache_evict：调用后删除缓存键"""

    @cacheable("order:{0}")
    async def get_order(oid):
        return f"order-{oid}"

    @cache_evict("order:{0}")
    async def del_order(oid):
        return f"del-{oid}"

    await get_order(3)
    assert await mem_cache.exists("order:3") is True
    await del_order(3)
    assert await mem_cache.exists("order:3") is False


@pytest.mark.asyncio
async def test_cacheable_ttl_arg(mem_cache):
    """@cacheable 支持 ttl 参数：写入带 TTL"""

    @cacheable("order:{0}", ttl=5)
    async def get_order(oid):
        return "v"

    await get_order(4)
    # MemoryCacheBackend 需暴露条目 TTL（若接口无则跳过）；此处仅验证不报错
    assert await mem_cache.exists("order:4") is True
