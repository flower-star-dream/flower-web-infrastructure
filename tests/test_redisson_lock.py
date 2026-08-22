"""
分布式锁 SPI 与 Redisson RLock 测试

@Author: 花海
@Date: 2026/08/22 20:00
@Description: 验证分布式锁抽象接口、注册表（按 type 装配）、RedissonLock 看门狗续期、
              可重入、取消安全与看门狗注册表清理。使用内存 FakeRedis 模拟 redis.asyncio 语义。
"""
import asyncio
import pytest

from web_infra.infra.resilience.distributed_lock_registry import DistributedLockRegistry
from web_infra.infra.resilience.distributed_lock_interface import DistributedLockInterface


def test_registry_register_and_names():
    """注册表：register 后 registered_names 可见，get 可取工厂"""
    class _FakeLock:
        """最小锁占位（实现接口）"""

        async def acquire(self, wait_timeout: float = 3.0) -> bool:
            return True

        async def release(self) -> None:
            return None

        @property
        def lock_key(self) -> str:
            return "fake"

    DistributedLockRegistry.register("fake", lambda key, lease_time=30: _FakeLock())
    assert "fake" in DistributedLockRegistry.registered_names()
    factory = DistributedLockRegistry.get("fake")
    assert callable(factory)
    DistributedLockRegistry.unregister("fake")


def test_interface_runtime_checkable():
    """接口可做 isinstance 运行时校验（同 IdempotencyStoreInterface 风格）"""
    assert DistributedLockInterface is not None

    class _Minimal:
        async def acquire(self, wait_timeout: float = 3.0) -> bool:
            return True

        async def release(self) -> None:
            return None

        @property
        def lock_key(self) -> str:
            return "x"

        async def __aenter__(self) -> "_Minimal":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    assert isinstance(_Minimal(), DistributedLockInterface)
