"""
消息分区选择器

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 消息分区选择抽象（规范 §9.2：按业务主键哈希选分区，分区内串行消费）。
              通过稳定的业务分区键（partition_key）哈希取模，保证同一业务主键的消息
              始终落入同一分区，从而在分区内按序串行消费（S9-2）。
"""
from __future__ import annotations

import zlib
from abc import ABC, abstractmethod


class MessageQueueSelector(ABC):
    """消息分区选择器（抽象基类）"""

    @abstractmethod
    def select(self, topic: str, partition_key: str | None, partition_count: int) -> int:
        """选择消息落区索引（分区号）。

        :param topic: 消息主题
        :param partition_key: 业务分区键（如订单号、用户号，None 表示无分区要求）
        :param partition_count: 分区总数（<=0 时返回 0）
        :return: 分区索引，范围 [0, partition_count)
        """
        raise NotImplementedError


class HashMessageQueueSelector(MessageQueueSelector):
    """哈希消息分区选择器（默认实现）

    基于 zlib.crc32 稳定哈希取模：相同 partition_key 恒得到相同分区（确定性），
    不同 partition_key 尽量均匀分布（规范 §9.2 按业务主键哈希选分区）。
    """

    def select(self, topic: str, partition_key: str | None, partition_count: int) -> int:
        """选择分区索引：无分区键或分区数非法时返回 0，否则按稳定哈希取模。"""
        if partition_count <= 0:
            return 0
        if not partition_key:
            return 0
        return zlib.crc32(partition_key.encode("utf-8")) % partition_count
