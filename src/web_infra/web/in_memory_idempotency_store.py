"""
内存幂等键存储

@Author: 花海
@Date: 2026/08/14 18:30
@Description: 基于内存字典 + asyncio.Lock 的幂等键存储（默认实现，单实例场景；规范 §12.6）。
              多实例需切换 RedisIdempotencyStore（SETNX 原子占用保证跨实例原子性）。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from web_infra.web.idempotency_store_interface import IdempotencyResult, IdempotencyStoreInterface


class InMemoryIdempotencyStore(IdempotencyStoreInterface):
    """内存幂等键存储（默认实现）

    @Stateful：进程内内存存储，单实例/单进程部署，多实例需替换为分布式实现（S1-1）。
    """

    def __init__(self) -> None:
        self._occupied: dict[str, float] = {}  # key -> expire_at（占用中）
        self._results: dict[str, tuple[IdempotencyResult, float]] = {}  # key -> (result, expire_at)
        self._lock = asyncio.Lock()

    async def try_occupy(self, key: str, ttl_seconds: int) -> bool:
        """原子占用：键未占用且无已缓存结果时成功"""
        async with self._lock:
            now = time.monotonic()
            self._expire(now)
            if key in self._occupied or key in self._results:
                return False
            self._occupied[key] = now + ttl_seconds
            return True

    async def set_result(self, key: str, result: IdempotencyResult, ttl_seconds: int) -> None:
        """保存结果并清除占用标记"""
        async with self._lock:
            now = time.monotonic()
            self._occupied.pop(key, None)
            self._results[key] = (result, now + ttl_seconds)

    async def get_result(self, key: str) -> IdempotencyResult | None:
        """读取结果（未完成返回 None）"""
        async with self._lock:
            now = time.monotonic()
            item = self._results.get(key)
            if item is None:
                return None
            result, expire_at = item
            if expire_at <= now:
                self._results.pop(key, None)
                return None
            return result

    async def release(self, key: str) -> None:
        """释放占用（业务异常时调用）"""
        async with self._lock:
            self._occupied.pop(key, None)

    def _expire(self, now: float) -> None:
        """清理过期键"""
        for key in [k for k, t in self._occupied.items() if t <= now]:
            self._occupied.pop(key, None)
        for key in [k for k, (_, t) in self._results.items() if t <= now]:
            self._results.pop(key, None)
