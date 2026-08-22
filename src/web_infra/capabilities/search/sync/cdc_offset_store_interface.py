"""
CDC 位点存储 SPI

@Author: 花海
@Date: 2026/08/22 15:00
@Description: CDC 消费位点存储契约（搜索引擎数据同步方案 §4.4）：断点续传的持久化载体。
              位点 key 形如 "{source}:{database}:{table}"，value 为数据源位点字符串
              （MySQL 为 "binlog_file:binlog_pos"）。save 为幂等覆盖，load 缺省返回 None（从当前位点起读）。
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class CdcOffsetStoreInterface(Protocol):
    """CDC 消费位点存储契约：断点续传的持久化载体"""

    async def save(self, key: str, position: str) -> None:
        """持久化位点（幂等覆盖）。

        :param key: 位点 key（形如 "{source}:{database}:{table}"）
        :param position: 数据源位点字符串（如 MySQL 的 "binlog_file:binlog_pos"）
        """
        ...

    async def load(self, key: str) -> Optional[str]:
        """读取位点；无记录返回 None（数据源从当前位置起读）。

        :param key: 位点 key
        :return: 位点字符串；不存在返回 None
        """
        ...
