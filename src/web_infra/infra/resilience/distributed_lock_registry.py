"""
分布式锁注册表

@Author: 花海
@Date: 2026/08/22 20:00
@Description: 分布式锁 SPI 注册表：按 type 名注册/查询锁工厂，装配期（app.lock.type）按名实例化；
              内置 redis / redisson 条目；自定义锁实现（ZooKeeper/etcd 等）经 register 注册后接入 create_app。
              与 CacheBackendRegistry 同风格（类级注册，全局装配；同名覆盖；未注册按名查询抛 KeyError）。
"""
from __future__ import annotations

from threading import Lock
from typing import Callable, ClassVar


#: 锁工厂签名：按 (redis_client, key, lease_time) 构造锁实例，
#: redis_client 由装配层（复用 cache 组件 RedisConfig）或调用方提供
LockFactory = Callable[..., object]


class DistributedLockRegistry:
    """分布式锁注册表（类级注册，全局装配；同名覆盖）"""

    _factories: ClassVar[dict[str, LockFactory]] = {}
    _lock = Lock()

    @classmethod
    def register(cls, name: str, factory: LockFactory, overwrite: bool = False) -> None:
        """注册锁工厂（同名默认拒绝，overwrite=True 覆盖）。

        :param name: type 名（与 yml app.lock.type 匹配）
        :param factory: 工厂，入参 (redis_client, key, lease_time)，返回锁实例
        :param overwrite: 同名已存在时是否显式覆盖
        :raises ValueError: 同名已存在且未显式覆盖
        """
        with cls._lock:
            existing = cls._factories.get(name)
            if existing is not None and not overwrite:
                raise ValueError(f"锁类型 {name} 已注册（覆盖需 register(..., overwrite=True)）")
            cls._factories[name] = factory

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销锁工厂（不存在时静默）"""
        with cls._lock:
            cls._factories.pop(name, None)

    @classmethod
    def get(cls, name: str) -> LockFactory:
        """按名查询工厂；未注册抛 KeyError（装配期由 create_app 捕获转 ConfigError）"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory

    @classmethod
    def registered_names(cls) -> list[str]:
        """已注册锁类型名清单"""
        with cls._lock:
            return list(cls._factories)


def _redis_lock_factory(redis_client, key: str, lease_time: int = 30):
    """内置 redis：Redis 分布式锁（SET NX PX + Lua 释放，静态租约）"""
    from web_infra.infra.resilience.redis_distributed_lock import DistributedLock

    return DistributedLock(redis_client, key=key, lease_time=lease_time)


def _redisson_lock_factory(redis_client, key: str, lease_time: int = 30):
    """内置 redisson：Redisson 风格 RLock（看门狗自动续期 + 可重入）"""
    from web_infra.infra.resilience.redisson_lock import RedissonLock

    return RedissonLock(redis_client, key=key, lease_time=lease_time)


# 内置锁类型条目（模块导入即注册，幂等）
DistributedLockRegistry.register("redis", _redis_lock_factory, overwrite=True)
DistributedLockRegistry.register("redisson", _redisson_lock_factory, overwrite=True)
