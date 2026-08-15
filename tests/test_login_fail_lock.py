"""
登录防爆破计数锁定单元测试

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 验证账号/IP 双维度失败计数、锁定阈值、解锁与 Redis 异常降级。
"""
import pytest
from redis.exceptions import RedisError

from web_infra.security import LoginFailLockService


class _FakeRedis:
    """内存模拟 redis.asyncio 的 incr/expire/set/exists/delete 语义"""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttl: dict[str, float] = {}

    async def incr(self, key: str) -> int:
        value = int(self._store.get(key, "0")) + 1
        self._store[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> bool:
        self._ttl[key] = seconds
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value
        if ex is not None:
            self._ttl[key] = ex

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                self._ttl.pop(key, None)
                removed += 1
        return removed


class _RaisingRedis:
    """所有操作抛 RedisError，用于验证降级路径"""

    async def incr(self, key: str) -> int:
        raise RedisError("redis down")

    async def expire(self, key: str, seconds: int) -> bool:
        raise RedisError("redis down")

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        raise RedisError("redis down")

    async def exists(self, key: str) -> int:
        raise RedisError("redis down")

    async def delete(self, *keys: str) -> int:
        raise RedisError("redis down")


@pytest.mark.asyncio
async def test_record_failure_increments_and_locks_user():
    """账号失败达到阈值后锁定"""
    redis = _FakeRedis()
    svc = LoginFailLockService(redis, max_user_fail_times=3, max_ip_fail_times=10)
    for _ in range(3):
        await svc.record_failure("alice", "1.1.1.1")
    assert await svc.is_locked("alice", "1.1.1.1") is True


@pytest.mark.asyncio
async def test_below_threshold_not_locked():
    """失败未达阈值不锁定"""
    redis = _FakeRedis()
    svc = LoginFailLockService(redis, max_user_fail_times=3, max_ip_fail_times=10)
    await svc.record_failure("alice", "1.1.1.1")
    await svc.record_failure("alice", "1.1.1.1")
    assert await svc.is_locked("alice", "1.1.1.1") is False


@pytest.mark.asyncio
async def test_ip_dimension_locks_independently():
    """IP 维度独立锁定：IP 达阈值锁定，账号维度未达阈值也因 IP 被锁"""
    redis = _FakeRedis()
    svc = LoginFailLockService(redis, max_user_fail_times=100, max_ip_fail_times=2)
    await svc.record_failure("alice", "1.1.1.1")
    await svc.record_failure("bob", "1.1.1.1")  # 不同账号、同一 IP
    assert await svc.is_locked("alice", "1.1.1.1") is True
    # 同 IP 锁定不影响其他 IP 下的账号
    assert await svc.is_locked("alice", "2.2.2.2") is False


@pytest.mark.asyncio
async def test_user_lock_only_affects_that_user():
    """账号锁定不波及其他账号"""
    redis = _FakeRedis()
    svc = LoginFailLockService(redis, max_user_fail_times=1, max_ip_fail_times=100)
    await svc.record_failure("alice", "1.1.1.1")
    assert await svc.is_locked("alice", "1.1.1.1") is True
    assert await svc.is_locked("bob", "1.1.1.1") is False


@pytest.mark.asyncio
async def test_clear_resets_lock():
    """登录成功后清除计数与锁定"""
    redis = _FakeRedis()
    svc = LoginFailLockService(redis, max_user_fail_times=2, max_ip_fail_times=2)
    await svc.record_failure("alice", "1.1.1.1")
    await svc.record_failure("alice", "1.1.1.1")
    assert await svc.is_locked("alice", "1.1.1.1") is True
    await svc.clear("alice", "1.1.1.1")
    assert await svc.is_locked("alice", "1.1.1.1") is False


@pytest.mark.asyncio
async def test_redis_error_degraded_not_locked():
    """Redis 异常降级：不锁定、可继续登录"""
    svc = LoginFailLockService(_RaisingRedis(), max_user_fail_times=1, max_ip_fail_times=1)
    await svc.record_failure("alice", "1.1.1.1")  # 不抛异常
    assert await svc.is_locked("alice", "1.1.1.1") is False  # 降级为不锁定
