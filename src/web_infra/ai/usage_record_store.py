"""
用量记录存储接口

@Author: 花海
@Date: 2026/08/14 15:00
@Description: Token 用量与成本记录持久化抽象（SPI，AI 规范 §5.2），
              默认仅结构化日志输出；业务可对接数据库等实现该接口做计费/审计。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from web_infra.ai.usage_record import UsageRecord


class UsageRecordStoreInterface(ABC):
    """用量记录存储接口"""

    @abstractmethod
    async def save(self, record: UsageRecord) -> None:
        """持久化一条用量记录"""
        raise NotImplementedError
