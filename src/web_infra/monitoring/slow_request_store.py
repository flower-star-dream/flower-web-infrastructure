"""
慢请求样本留存（有界环形缓存）

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 按规范 §18.5.2 留存慢请求样本（TraceId/耗时/脱敏路径/方法/状态码/参数摘要/各阶段耗时），
              供运维回放排查。样本仅存内存（deque 有界），不持久化；写入前已由调用方完成
              路径归一化与参数脱敏（复用 web_infra.logging.masking.mask）。单例 + 线程安全。
"""
from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any

# 慢请求样本缓存上限（有界，防止内存无限增长）
SLOW_REQUEST_SAMPLE_MAXLEN = 100


class SlowRequestStore:
    """慢请求样本有界环形缓存（单例，线程安全，仅存内存）"""

    _instance: "SlowRequestStore | None" = None
    # S16-2 豁免：临界区为纯内存操作，无 I/O 阻塞，不适用 3s 获取超时
    _instance_lock = Lock()

    def __init__(self, maxlen: int = SLOW_REQUEST_SAMPLE_MAXLEN) -> None:
        """初始化样本缓存。

        :param maxlen: 环形缓存上限（超出后自动丢弃最旧样本）
        """
        self._maxlen = maxlen
        self._samples: deque[dict[str, Any]] = deque(maxlen=maxlen)
        # S16-2 豁免：临界区为纯内存操作，无 I/O 阻塞，不适用 3s 获取超时
        self._lock = Lock()

    @classmethod
    def instance(cls) -> "SlowRequestStore":
        """获取全局单例（懒初始化，线程安全）"""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    def record(self, sample: dict[str, Any]) -> None:
        """写入一条慢请求样本（最近写入的样本排在最前）"""
        with self._lock:
            self._samples.appendleft(sample)

    def recent(self, limit: int | None = None) -> list[dict[str, Any]]:
        """返回最近 N 条样本（默认全部，按写入时间倒序）。

        :param limit: 返回条数上限；None 表示全部
        :return: 样本列表（内部副本，修改不影响缓存）
        """
        with self._lock:
            items = list(self._samples)
        return items if limit is None else items[:limit]

    def clear(self) -> None:
        """清空全部样本（测试/运维手动清理用）"""
        with self._lock:
            self._samples.clear()

    @property
    def size(self) -> int:
        """当前样本条数"""
        with self._lock:
            return len(self._samples)
