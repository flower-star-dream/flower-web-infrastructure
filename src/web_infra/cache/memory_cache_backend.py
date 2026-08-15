"""
内存缓存后端

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 内存缓存后端：带容量上限 + TTL 淘汰（供单实例/测试场景使用，规范 §8 / §16.5）。
              支持空值占位（规范 §8.2 防缓存穿透）与 TTL 抖动（规范 §8.3 防缓存雪崩）。
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import OrderedDict
from typing import Any

from web_infra.cache.cache_backend_interface import EMPTY_TTL_LIMIT_SECONDS, CacheBackendInterface
from web_infra.cache.cache_config import CacheConfig
from web_infra.monitoring.cache_metrics import CacheMetrics

# 统一日志入口（规范 §17）
_logger = logging.getLogger("web_infra")

# 缓存实现名（低基数标签，对应 app.cache.type）
_CACHE_NAME = "memory"

# 空值占位标记（区别于真实缓存值；get 对空值返回 None，is_empty 识别空值）
_EMPTY = object()


class MemoryCacheBackend(CacheBackendInterface):
    """内存缓存后端：带容量上限 + TTL 淘汰（供单实例/测试场景使用）

    @Stateful：进程内内存存储，单实例/单进程部署，多实例需替换为分布式缓存（S1-1）。
    本地缓存 TTL 自动钳制为分布式 TTL 的 1/3（规范 §8.3，防缓存雪崩、避免本地缓存拖长分布式 TTL 语义）。
    """

    def __init__(self, config: CacheConfig | None = None) -> None:
        self.config = config or CacheConfig()
        # OrderedDict 记录插入顺序，便于超容量时淘汰最旧项
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = asyncio.Lock()

    def _now(self) -> float:
        """返回当前单调时间（秒）"""
        return time.monotonic()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            item = self._store.get(key)
            if item is None:
                CacheMetrics.record_operation(_CACHE_NAME, "get", hit=False)
                return None
            value, expire_at = item
            if expire_at < self._now():
                self._store.pop(key, None)
                CacheMetrics.record_operation(_CACHE_NAME, "get", hit=False)
                return None
            # 空值占位对调用方表现为未命中（防穿透：调用方自行用 is_empty 区分）
            if value is _EMPTY:
                CacheMetrics.record_operation(_CACHE_NAME, "get", hit=False)
                return None
            CacheMetrics.record_operation(_CACHE_NAME, "get", hit=True)
            return value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        ttl_jitter_seconds: float | None = None,
    ) -> None:
        """写入缓存。

        :param ttl: 过期秒数（None 使用默认 TTL）
        :param ttl_jitter_seconds: TTL 抖动上限（秒，None 使用配置默认，0 关闭；规范 §8.3 防雪崩）
        """
        expire_ttl: float = self.config.default_ttl if ttl is None else ttl
        # 规范 §8.3：本地缓存 TTL 不得超过分布式 TTL 的比例上限（默认 1/3）。
        # 在叠加抖动前判断并钳制，保证生效 TTL 不拖长分布式 TTL 语义；
        # remote_default_ttl <= 0 时跳过钳制，避免除零/负上限。
        remote_ttl = self.config.remote_default_ttl
        if remote_ttl > 0:
            ttl_limit: float = remote_ttl * self.config.local_ttl_ratio_limit
            if expire_ttl > ttl_limit:
                _logger.warning(
                    "本地缓存 TTL 超限被钳制: key=%s ttl=%ss -> %ss（分布式 TTL %ss 的 %s，规范 §8.3）",
                    key,
                    expire_ttl,
                    ttl_limit,
                    remote_ttl,
                    self.config.local_ttl_ratio_limit,
                )
                expire_ttl = ttl_limit
        jitter = (
            self.config.default_ttl_jitter_seconds
            if ttl_jitter_seconds is None
            else ttl_jitter_seconds
        )
        if jitter > 0:
            # 抖动叠加 [0, jitter) 秒，使同 TTL 的热点 Key 错峰过期（规范 §8.3）
            expire_ttl += random.uniform(0, jitter)
        async with self._lock:
            self._store[key] = (value, self._now() + expire_ttl)
            self._store.move_to_end(key)
            # 超容量淘汰最旧项
            while len(self._store) > self.config.max_size:
                self._store.popitem(last=False)
        CacheMetrics.record_operation(_CACHE_NAME, "set")

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)
        CacheMetrics.record_operation(_CACHE_NAME, "delete")

    async def exists(self, key: str) -> bool:
        return await self.get(key) is not None

    async def set_empty(self, key: str, ttl: int = 60) -> None:
        """写入空值占位（数据不存在标记，规范 §8.2 防缓存穿透）。

        :param ttl: 过期秒数（默认 60，上限 120s，超限自动钳制）
        """
        ttl = min(max(int(ttl), 1), EMPTY_TTL_LIMIT_SECONDS)
        async with self._lock:
            self._store[key] = (_EMPTY, self._now() + ttl)
            self._store.move_to_end(key)
            while len(self._store) > self.config.max_size:
                self._store.popitem(last=False)
        CacheMetrics.record_operation(_CACHE_NAME, "set_empty")

    async def is_empty(self, key: str) -> bool:
        """判断是否处于空值占位状态（TTL 过期后自动失效返回 False）"""
        async with self._lock:
            item = self._store.get(key)
            if item is None:
                return False
            value, expire_at = item
            if expire_at < self._now():
                self._store.pop(key, None)
                return False
            return value is _EMPTY
