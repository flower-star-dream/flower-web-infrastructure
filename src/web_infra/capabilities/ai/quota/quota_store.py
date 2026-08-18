"""
配额计数存储接口

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 配额计数存储抽象（SPI，AI 规范 §5.3），
              默认内存实现；多实例需实现 Redis 等共享存储（INCR + TTL 窗口）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class QuotaCounter:
    """窗口内配额计数"""

    calls: int = 0      # 调用次数
    tokens: int = 0     # Token 用量
    cost: float = 0.0   # 成本（元）


class QuotaStoreInterface(ABC):
    """配额计数存储接口"""

    @abstractmethod
    async def incr(self, key: str, *, calls: int, tokens: int, cost: float, window_seconds: int) -> QuotaCounter:
        """按窗口累加计数（窗口过期自动重置），返回累加后的计数。

        :param key: 配额计数 Key（含维度与 scope）
        :param calls: 本次调用次数增量
        :param tokens: 本次 Token 增量
        :param cost: 本次成本增量
        :param window_seconds: 统计窗口（秒），首次写入时设置 TTL
        """
        raise NotImplementedError
