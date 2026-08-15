"""
熔断器配置

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 熔断参数（规范 §7.4 / 附录 A.5）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CircuitBreakerConfig:
    """熔断参数（规范 §7.4 / 附录 A.5）"""

    failure_rate_threshold: float = 0.5          # 错误率阈值（50%）
    slow_call_rate_threshold: float = 0.8        # 慢调用比例阈值（80%）
    slow_call_duration_threshold: float = 1.0    # 慢调用判定阈值（秒）
    wait_duration_in_open_state: float = 30.0    # OPEN 状态等待时间（秒）
    permitted_calls_in_half_open_state: int = 5  # HALF_OPEN 允许试探调用数
    minimum_number_of_calls: int = 10            # 评估熔断所需最小样本数
    window_size: int = 20                        # 滑动窗口容量
