"""
令牌桶限流器

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 令牌桶限流器，遵循规范 §7.3（令牌桶平滑限流）。
              支持按 QPS 限流与突发（burst）容量，供统一入口/服务层/核心接口多层防护使用。
"""
from __future__ import annotations

import threading
import time

from web_infra.infra.resilience.rate_limit_config import RateLimitConfig


class TokenBucketRateLimiter:
    """令牌桶限流器：以固定速率补充令牌，请求消耗令牌，令牌不足即拒绝"""

    def __init__(self, name: str, config: RateLimitConfig) -> None:
        self.name = name
        self.config = config
        # 桶容量 = 突发量（burst），qps 仅决定补充速率（规范 §7.3 令牌桶）
        self._capacity = config.burst
        self._tokens = self._capacity
        self._last_refill = time.monotonic()
        # S16-2 豁免：临界区为纯内存操作，无 I/O 阻塞，不适用 3s 获取超时
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """按时间差补充令牌，上限为桶容量"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self.config.qps)
        self._last_refill = now

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """尝试获取 tokens 个令牌，成功返回 True，否则返回 False（线程安全）"""
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def retry_after_seconds(self, tokens: float = 1.0) -> float:
        """获取指定数量令牌所需等待秒数（用于 429 Retry-After 响应头；当前足够则返回 0）"""
        with self._lock:
            self._refill()
            deficit = tokens - self._tokens
            if deficit <= 0:
                return 0.0
            if self.config.qps <= 0:
                return float("inf")  # 无补充速率，永远无法满足
            return deficit / self.config.qps

    def acquire_or_false(self) -> bool:
        """单令牌获取的便捷方法"""
        return self.try_acquire(1)
