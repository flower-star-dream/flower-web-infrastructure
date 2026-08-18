"""
内存消息幂等键存储

@Author: 花海
@Date: 2026/08/14 19:00
@Description: 基于内存字典 + asyncio.Lock 的消息消费幂等键存储（默认实现，单实例场景；规范 §9.2）。
              多实例需切换 Redis 实现（SETNX 原子性）。
"""
from __future__ import annotations

import asyncio
import time

from web_infra.capabilities.mq.message_idempotency_store_interface import MessageIdempotencyStoreInterface


class InMemoryMessageIdempotencyStore(MessageIdempotencyStoreInterface):
    """内存消息消费幂等键存储（默认实现）

    @Stateful：进程内内存存储，单实例/单进程部署，多实例需替换为分布式实现（S1-1）。
    仅限单事件循环访问（asyncio.Lock 不跨线程互斥），跨线程/跨循环场景请改用线程安全或分布式实现。
    """

    def __init__(self) -> None:
        self._store: dict[str, float] = {}  # key -> expire_at
        self._lock = asyncio.Lock()

    async def try_consume(self, key: str, ttl_seconds: int) -> bool:
        """原子写入：键不存在则成功（首次消费），存在则视为重复"""
        async with self._lock:
            now = time.monotonic()
            for expired in [k for k, t in self._store.items() if t <= now]:
                self._store.pop(expired, None)
            if key in self._store:
                return False
            self._store[key] = now + ttl_seconds
            return True

    async def release(self, key: str) -> None:
        """回滚占用（业务失败重试）"""
        async with self._lock:
            self._store.pop(key, None)
