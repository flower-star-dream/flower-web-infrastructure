"""
限流配置

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 限流配置（规范 §7.3 / 附录 A.4）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitConfig:
    """限流配置（规范 §7.3 / 附录 A.4）"""

    qps: float = 1000.0     # 每秒令牌补充速率
    burst: float = 100.0    # 桶容量（允许突发量）
