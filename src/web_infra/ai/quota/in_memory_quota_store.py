"""
内存配额计数存储

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 基于内存字典 + asyncio.Lock 的配额计数存储（默认实现，单实例场景），
              窗口过期自动重置；多实例需切换 Redis 等共享实现（QuotaStoreInterface）。
"""
from __future__ import annotations

import asyncio
import time

from web_infra.ai.quota.quota_store import QuotaCounter, QuotaStoreInterface


class InMemoryQuotaStore(QuotaStoreInterface):
    """内存配额计数存储（默认实现）

    @Stateful：进程内内存存储，单实例/单进程部署，多实例需替换为分布式实现（S1-1）。
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[QuotaCounter, float]] = {}  # key -> (counter, expire_at)
        self._lock = asyncio.Lock()

    async def incr(self, key: str, *, calls: int, tokens: int, cost: float, window_seconds: int) -> QuotaCounter:
        async with self._lock:
            now = time.monotonic()
            # 惰性清理窗口已过期的计数键（按不同 key 维度隔离计数，防键集合无限增长）
            for expired in [k for k, (_, expire_at) in self._store.items() if expire_at <= now]:
                self._store.pop(expired, None)
            item = self._store.get(key)
            if item is None or item[1] <= now:  # 无记录或窗口已过期：重置
                counter = QuotaCounter(calls=calls, tokens=tokens, cost=cost)
                self._store[key] = (counter, now + window_seconds)
                return counter
            counter, expire_at = item
            counter.calls += calls
            counter.tokens += tokens
            counter.cost += cost
            return counter
