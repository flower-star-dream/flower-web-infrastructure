"""
分布式锁注册表

@Author: 花海
@Date: 2026/08/22 20:00
@Description: 分布式锁 SPI 注册表：按 type 名注册/查询锁工厂，装配期（app.lock.type）按名实例化；
              内置 redis / redisson 条目；自定义锁实现（ZooKeeper/etcd 等）经 register 注册后接入 create_app。
              继承 SpiRegistry 基类：内置默认落框架命名空间（受保护），用户同名覆盖经默认命名空间解析，
              register 同名默认拒绝（overwrite=True 覆盖），与 CacheBackendRegistry 同风格。
"""
from __future__ import annotations

from typing import Callable

from web_infra.core.spi import SpiRegistry


#: 锁工厂签名：按 (redis_client, key, lease_time) 构造锁实例，
#: redis_client 由装配层（复用 cache 组件 RedisConfig）或调用方提供
LockFactory = Callable[..., object]


class DistributedLockRegistry(SpiRegistry):
    """分布式锁注册表（类级注册，全局装配；同名覆盖）"""


def _redis_lock_factory(redis_client, key: str, lease_time: int = 30):
    """内置 redis：Redis 分布式锁（SET NX PX + Lua 释放，静态租约）"""
    from web_infra.infra.resilience.redis_distributed_lock import DistributedLock

    return DistributedLock(redis_client, key=key, lease_time=lease_time)


def _redisson_lock_factory(redis_client, key: str, lease_time: int = 30):
    """内置 redisson：Redisson 风格 RLock（看门狗自动续期 + 可重入）"""
    from web_infra.infra.resilience.redisson_lock import RedissonLock

    return RedissonLock(redis_client, key=key, lease_time=lease_time)


# 内置锁类型条目（模块导入即注册，幂等）
DistributedLockRegistry.register(
    "redis", _redis_lock_factory, overwrite=True, namespace=DistributedLockRegistry.FRAMEWORK_NAMESPACE
)
DistributedLockRegistry.register(
    "redisson", _redisson_lock_factory, overwrite=True, namespace=DistributedLockRegistry.FRAMEWORK_NAMESPACE
)
