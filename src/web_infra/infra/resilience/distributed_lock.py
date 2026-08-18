"""
分布式锁

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 基于 Redis 的分布式锁（规范 §16.4：必须带租约/超时、tryLock；§23.2）。
              使用 SET key token NX PX 原子加锁 + Lua 脚本原子释放（校验持有者 token，防误删他人锁）。
              支持异步上下文管理器（async with），租约到期自动释放，避免死锁。
"""
from __future__ import annotations

import asyncio
import secrets
from typing import Any

from web_infra.infra.constants import CacheKeyBuilder

# Lua 释放脚本：仅当持有者 token 匹配时才删除（防误删）
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class DistributedLock:
    """Redis 分布式锁（带租约、获取超时、持有者 token 校验）

    用法：
        lock = DistributedLock(redis_client, key="order:1001", lease_time=30)
        async with lock:
            ...  # 临界区

    或显式调用：
        ok = await lock.acquire(wait_timeout=3)
        if ok:
            try:
                ...
            finally:
                await lock.release()
    """

    def __init__(
        self,
        redis: Any,
        key: str,
        lease_time: int = 30,
    ) -> None:
        """初始化分布式锁。

        :param redis: redis.asyncio.Redis 兼容客户端（需提供 set/eval/delete 方法）
        :param key: 锁的业务 Key（自动拼缓存 Key 前缀与版本，规范 §5.7）
        :param lease_time: 租约时长（秒），到期自动释放，默认 30s（规范 §16.4 持有上限）
        """
        if lease_time <= 0:
            raise ValueError("lease_time 必须大于 0")
        self._redis = redis
        self._lock_key = CacheKeyBuilder.build(CacheKeyBuilder.DISTRIBUTED_LOCK, key=key)
        self._lease_time = lease_time
        self._token: str | None = None

    @property
    def lock_key(self) -> str:
        """锁对应的完整 Redis Key"""
        return self._lock_key

    async def acquire(self, wait_timeout: float = 3.0) -> bool:
        """尝试获取锁，最多等待 wait_timeout 秒（tryLock，规范 §16.4 锁获取超时默认 3s）。

        :param wait_timeout: 获取锁的最大等待时长（秒）
        :return: 是否获取成功
        """
        token = secrets.token_urlsafe(16)
        deadline = asyncio.get_running_loop().time() + wait_timeout
        while True:
            acquired = await self._redis.set(
                self._lock_key,
                token,
                nx=True,
                px=int(self._lease_time * 1000),
            )
            if acquired:
                self._token = token
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(0.05)

    async def release(self) -> None:
        """释放锁（仅持有者 token 匹配时删除，避免误删他人新持有的锁）"""
        if self._token is None:
            return
        await self._redis.eval(_RELEASE_SCRIPT, 1, self._lock_key, self._token)
        self._token = None

    async def __aenter__(self) -> "DistributedLock":
        """异步上下文管理器入口：未获取到锁抛 TimeoutError"""
        if not await self.acquire():
            raise TimeoutError(f"获取分布式锁超时: {self._lock_key}")
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """异步上下文管理器出口：释放锁"""
        await self.release()
