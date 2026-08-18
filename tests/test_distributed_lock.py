"""
分布式锁单元测试

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 用内存 FakeRedis 验证互斥、租约过期自动释放、tryLock 超时、持有者 token 防误删（规范 §16.4）。
"""
import asyncio
import time

import pytest

from web_infra.infra.resilience import DistributedLock


class _FakeRedis:
    """内存模拟 redis.asyncio 的 set(nx/px) 与 eval 语义（支持时钟注入以便测试租约过期）"""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}  # key -> (token, expire_at_ms)
        self._now_ms: float = 0.0

    def advance(self, ms: float) -> None:
        """推进模拟时钟（毫秒）"""
        self._now_ms += ms

    def _is_expired(self, key: str) -> bool:
        if key not in self._store:
            return False
        return self._store[key][1] <= self._now_ms

    def _purge_expired(self, key: str) -> None:
        if self._is_expired(key):
            del self._store[key]

    async def set(self, key: str, value: str, nx: bool = False, px: int | None = None) -> bool:
        self._purge_expired(key)
        if nx and key in self._store:
            return False
        expire_at = (self._now_ms + px) if px is not None else float("inf")
        self._store[key] = (value, expire_at)
        return True

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        self._purge_expired(key)
        current = self._store.get(key)
        if current is not None and current[0] == token:
            del self._store[key]
            return 1
        return 0

    async def delete(self, key: str) -> int:
        return 1 if self._store.pop(key, None) is not None else 0


@pytest.mark.asyncio
async def test_mutex_two_locks():
    """互斥：同 key 第二个锁获取失败"""
    redis = _FakeRedis()
    lock1 = DistributedLock(redis, key="biz:1001", lease_time=30)
    lock2 = DistributedLock(redis, key="biz:1001", lease_time=30)
    assert await lock1.acquire(wait_timeout=0.1) is True
    assert await lock2.acquire(wait_timeout=0.1) is False


@pytest.mark.asyncio
async def test_release_allows_other_lock():
    """释放后同 key 其他锁可获取"""
    redis = _FakeRedis()
    lock1 = DistributedLock(redis, key="biz:1001")
    lock2 = DistributedLock(redis, key="biz:1001")
    assert await lock1.acquire(wait_timeout=0.1) is True
    await lock1.release()
    assert await lock2.acquire(wait_timeout=0.1) is True


@pytest.mark.asyncio
async def test_lease_expiry_auto_release():
    """租约过期后锁自动释放（其他锁可获取）"""
    redis = _FakeRedis()
    lock1 = DistributedLock(redis, key="biz:1001", lease_time=2)
    lock2 = DistributedLock(redis, key="biz:1001", lease_time=30)
    assert await lock1.acquire(wait_timeout=0.1) is True
    redis.advance(3000)  # 租约 2s 已过
    assert await lock2.acquire(wait_timeout=0.1) is True


@pytest.mark.asyncio
async def test_stale_lock_release_does_not_delete_others():
    """防误删：旧锁释放时不得删除新持有者的锁"""
    redis = _FakeRedis()
    stale = DistributedLock(redis, key="biz:1001", lease_time=1)
    assert await stale.acquire(wait_timeout=0.1) is True
    redis.advance(2000)  # 旧锁租约过期
    fresh = DistributedLock(redis, key="biz:1001", lease_time=30)
    assert await fresh.acquire(wait_timeout=0.1) is True
    await stale.release()  # 旧持有者释放（token 不匹配，不应删除）
    assert redis._store.get(stale.lock_key) is not None  # 新锁仍存在


@pytest.mark.asyncio
async def test_context_manager_success():
    """异步上下文管理器：正常进入/退出"""
    redis = _FakeRedis()
    lock = DistributedLock(redis, key="biz:1001")
    entered = False
    async with lock:
        entered = True
        assert redis._store.get(lock.lock_key) is not None
    assert entered is True
    assert lock.lock_key not in redis._store


@pytest.mark.asyncio
async def test_context_manager_timeout_raises():
    """异步上下文管理器：获取超时抛 TimeoutError"""
    redis = _FakeRedis()
    holder = DistributedLock(redis, key="biz:1001", lease_time=30)
    assert await holder.acquire(wait_timeout=0.1) is True
    lock = DistributedLock(redis, key="biz:1001", lease_time=30)
    with pytest.raises(TimeoutError):
        async with lock:
            pass


@pytest.mark.asyncio
async def test_invalid_lease_time():
    """lease_time 非法值抛 ValueError"""
    redis = _FakeRedis()
    with pytest.raises(ValueError):
        DistributedLock(redis, key="biz:1001", lease_time=0)
