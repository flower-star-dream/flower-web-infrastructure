"""
分布式锁抽象接口

@Author: 花海
@Date: 2026/08/22 20:00
@Description: 分布式锁统一抽象（对标 Spring RedissonLock / RLock 语义）：提供加锁、释放、
              锁 Key 与异步上下文管理器。屏蔽底层实现差异（Redis 静态租约 / Redisson 看门狗续期，
              后续可扩展 ZooKeeper / etcd 等）。承接现有 DistributedLock 契约（acquire/release/lock_key）。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DistributedLockInterface(Protocol):
    """分布式锁抽象接口。

    - acquire(wait_timeout)：tryLock 获取锁（返回 bool；含获取超时语义）；
    - release()：释放锁（仅持有者 token 匹配，防误删他人锁）；
    - lock_key：锁对应的完整 Key（含前缀/版本）。
    - __aenter__/__aexit__：异步上下文管理器（进入未获取到抛 TimeoutError，退出自动 release）。
    """

    @property
    def lock_key(self) -> str:
        """锁对应的完整 Key"""
        ...

    async def acquire(self, wait_timeout: float = 3.0) -> bool:
        """尝试获取锁，最多等待 wait_timeout 秒（tryLock）。

        :param wait_timeout: 获取锁的最大等待时长（秒）
        :return: 是否获取成功
        """
        ...

    async def release(self) -> None:
        """释放锁（仅持有者 token 匹配时释放，避免误删他人新持有的锁）"""
        ...

    async def __aenter__(self) -> "DistributedLockInterface":
        """异步上下文管理器入口：未获取到锁抛 TimeoutError"""
        ...

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """异步上下文管理器出口：释放锁"""
        ...
