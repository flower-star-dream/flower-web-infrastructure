"""
限额计数存储（LimitCounterStore）

@Author: 花海
@Date: 2026/08/17
@Description: 限额/频次计数存储 SPI（规范 §9.1/§9.2）：Decimal 精确累计 + 原子更新（防并发超限，
              §9.4 红线：禁止浮点/非原子）。时间窗口桶按 (key, bucket) 组织，窗口过期自动重置。
              默认 InMemory 实现（单实例/测试）；生产用 Redis（实时频次判断以 Redis 为准，
              落库仅用于重启恢复，§9.2 频次存储约束）。
"""
from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class LimitCounterStoreInterface(Protocol):
    """限额/频次计数存储抽象接口（业务按 Redis/DB 实现，跨实例共享）"""

    async def add_and_get(self, key: str, amount: Decimal, window_seconds: int = 0) -> Decimal:
        """窗口计数累加并返回累计值：window_seconds > 0 按时间窗口桶计数（到期重置），
        否则永久累计（日/月累计由调用方构造含日/月前缀的 key）。金额 Decimal 精确累加。"""
        ...


class InMemoryLimitCounterStore:
    """内存限额/频次计数存储（单实例/测试；生产用 Redis）"""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, int], Decimal] = {}  # (key, bucket) -> 累计值
        self._lock = asyncio.Lock()

    async def add_and_get(self, key: str, amount: Decimal, window_seconds: int = 0) -> Decimal:
        """计数累加（原子，asyncio.Lock）：窗口过期重置后从当前值起算"""
        async with self._lock:
            bucket = self._bucket(window_seconds)
            stored = self._counters.get((key, bucket), Decimal("0"))
            total = stored + amount
            self._counters[(key, bucket)] = total
            self._cleanup()
            return total

    def _bucket(self, window_seconds: int) -> int:
        """时间窗口桶标识（窗口 0 = 永久累计桶）"""
        if window_seconds <= 0:
            return 0
        return int(time.time()) // window_seconds

    def _cleanup(self) -> None:
        """清理过期窗口桶（防内存无限增长：仅保留最近一个窗口）"""
        now_bucket = self._bucket(3600)
        stale = [k for k in self._counters if k[1] != 0 and k[1] < now_bucket - 1]
        for key in stale:
            self._counters.pop(key, None)
