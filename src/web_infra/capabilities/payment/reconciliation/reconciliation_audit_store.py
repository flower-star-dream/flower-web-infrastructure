"""
对账审计存储（ReconciliationAuditStore）

@Author: 花海
@Date: 2026/08/17
@Description: 对账审计存储（规范 §6.6/§8.3）：每次对账的差异清单、处理动作、处理人、处理时间
              只增不改（不可覆盖删除），携带账期/渠道/差异统计，支撑补对账与资金审计追溯。
              提供存储 SPI 与内存默认实现（RLock 并发安全，append 与防重查询原子）；
              生产用 MySQL 审计表（只增，含唯一自增主键）。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any, Protocol, runtime_checkable

from web_infra.capabilities.payment.reconciliation.reconciliation_difference import ReconciliationDifference


@dataclass
class ReconciliationAuditRecord:
    """对账审计记录（每次对账一轮一条，含差异明细与统计）"""

    audit_id: str = ""  # 审计记录号（缺省由存储生成）
    channel: str = ""  # 渠道名
    biz_date: str = ""  # 账期（YYYY-MM-DD，T-1）
    total_count: int = 0  # 账单行数
    difference_count: int = 0  # 差异数
    difference_types: dict[str, int] = field(default_factory=dict)  # 差异类型分布（§8.6 对账日志）
    differences: list[ReconciliationDifference] = field(default_factory=list)  # 差异清单（§6.6）
    created_at: datetime | None = None  # 对账时间


@runtime_checkable
class ReconciliationAuditStoreInterface(Protocol):
    """对账审计存储抽象接口（业务按数据库实现，只增不改）"""

    async def append(self, record: ReconciliationAuditRecord, session: Any | None = None) -> ReconciliationAuditRecord:
        """写入对账审计记录（只增，幂等：同 audit_id 已存在返回已有记录）"""
        ...

    async def find_by_channel_and_date(self, channel: str, biz_date: str) -> ReconciliationAuditRecord | None:
        """按（渠道 + 账期）查对账审计（对账任务防重：同一账期只对账一次，§6.5）"""
        ...


class InMemoryReconciliationAuditStore:
    """内存对账审计存储（单实例/测试；生产用 MySQL 审计表）"""

    def __init__(self) -> None:
        self._records: dict[str, ReconciliationAuditRecord] = {}
        self._by_key: dict[tuple[str, str], ReconciliationAuditRecord] = {}
        self._lock = RLock()

    async def append(self, record: ReconciliationAuditRecord, session: Any | None = None) -> ReconciliationAuditRecord:
        """写入审计记录（只增不改；同 audit_id 幂等；RLock 并发安全）"""
        with self._lock:
            if not record.audit_id:
                record.audit_id = uuid.uuid4().hex
            if record.created_at is None:
                record.created_at = datetime.now()
            existing = self._records.get(record.audit_id)
            if existing is not None:
                return existing
            self._records[record.audit_id] = record
            self._by_key[(record.channel, record.biz_date)] = record
            return record

    async def find_by_channel_and_date(self, channel: str, biz_date: str) -> ReconciliationAuditRecord | None:
        """按（渠道 + 账期）查审计记录（防重依据；与 append 同锁保证原子）"""
        with self._lock:
            return self._by_key.get((channel, biz_date))
