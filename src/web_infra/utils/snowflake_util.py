"""
雪花算法工具

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 生成分布式唯一 ID（Twitter Snowflake 算法），配合 BigIntJSONResponse 防止前端 JS 精度丢失。
"""
from __future__ import annotations

import logging
import os
import threading

from web_infra.utils.date_util import DateUtil


class SnowflakeUtil:
    """雪花算法 ID 生成器：64 位 = 1 符号 + 41 时间戳 + 10 机器ID + 12 序列号"""

    EPOCH = 1704067200000  # 起始时间戳（2024-01-01）
    WORKER_ID_BITS = 10
    SEQUENCE_BITS = 12
    MAX_WORKER_ID = (1 << WORKER_ID_BITS) - 1
    MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1
    WORKER_ID_SHIFT = SEQUENCE_BITS
    TIMESTAMP_SHIFT = SEQUENCE_BITS + WORKER_ID_BITS

    def __init__(self, worker_id: int = 0) -> None:
        if worker_id < 0 or worker_id > self.MAX_WORKER_ID:
            raise ValueError(f"worker_id 必须在 0-{self.MAX_WORKER_ID} 之间")
        self.worker_id = worker_id
        self.sequence = 0
        self.last_timestamp = -1
        # S16-2 豁免：临界区为纯内存操作，无 I/O 阻塞，不适用 3s 获取超时
        self._lock = threading.Lock()

    def next_id(self) -> int:
        """生成下一个唯一 ID"""
        with self._lock:
            timestamp = self._current_timestamp()
            if timestamp < self.last_timestamp:
                raise RuntimeError("时钟回拨，拒绝生成 ID")
            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & self.MAX_SEQUENCE
                if self.sequence == 0:
                    timestamp = self._wait_next_millis(timestamp)
            else:
                self.sequence = 0
            self.last_timestamp = timestamp
            return (
                ((timestamp - self.EPOCH) << self.TIMESTAMP_SHIFT)
                | (self.worker_id << self.WORKER_ID_SHIFT)
                | self.sequence
            )

    def _current_timestamp(self) -> int:
        """获取当前毫秒时间戳"""
        return DateUtil.timestamp_ms()

    def _wait_next_millis(self, last_timestamp: int) -> int:
        """等待下一毫秒"""
        timestamp = self._current_timestamp()
        while timestamp <= last_timestamp:
            timestamp = self._current_timestamp()
        return timestamp


# worker_id 延迟读取（2026-08-17）：.env 文件由 web_infra 包导入时（web_infra/__init__.py）提前加载，
# 但为杜绝任何路径下模块级立即读取早于 .env 加载（雪花 ID 恒为默认 0 并告警），
# 改为首次生成 ID 时读取 SNOWFLAKE_WORKER_ID 并构造单例。
_worker_id: int | None = None
_snowflake: SnowflakeUtil | None = None


def _get_snowflake() -> SnowflakeUtil:
    """获取雪花生成器单例：首次调用时读取 SNOWFLAKE_WORKER_ID（此时 .env 已加载）并构造。

    :return: SnowflakeUtil 单例
    """
    global _worker_id, _snowflake
    if _snowflake is None:
        _worker_id = int(os.getenv("SNOWFLAKE_WORKER_ID", "0"))
        if _worker_id == 0:
            # 多实例部署未区分 worker_id 时，同一毫秒内不同实例可能生成重复 ID（仅配置风险，不影响单实例）
            logging.getLogger("web_infra").warning(
                "SNOWFLAKE_WORKER_ID 未配置（默认 0）：多实例部署必须为每个实例配置唯一 worker_id，"
                "否则同一毫秒内不同实例可能生成重复雪花 ID"
            )
        _snowflake = SnowflakeUtil(worker_id=_worker_id)
    return _snowflake


def snowflake_id() -> int:
    """生成雪花 ID 的便捷函数"""
    return _get_snowflake().next_id()
