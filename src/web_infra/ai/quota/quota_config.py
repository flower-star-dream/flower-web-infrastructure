"""
配额配置

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 模型调用配额配置（AI 规范 §5.3/§6.2）：调用次数/Token/成本预算 + 统计窗口。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuotaConfig:
    """配额配置（0 表示该维度不限制）"""

    max_calls: int = 0          # 窗口内最大调用次数（0 不限）
    max_tokens: int = 0         # 窗口内最大 Token 用量（0 不限）
    max_cost: float = 0.0       # 窗口内最大成本预算（元，0 不限）
    window_seconds: int = 3600  # 统计窗口（秒，默认 1 小时）
