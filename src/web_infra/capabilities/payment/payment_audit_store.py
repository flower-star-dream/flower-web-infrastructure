"""
支付审计存储（PaymentAuditStore）

@Author: 花海
@Date: 2026/08/17
@Description: 支付全链路审计存储（规范 §8.3）：下单/回调（含原始报文）/入账/退款/冲正/对账差异
              只增不改（不可覆盖删除），携带 TraceId/订单号/渠道交易号支撑全链路追溯（§8.3）。
              敏感信息脱敏（§8.3：凭证/密钥/完整卡号禁止落审计）。提供存储 SPI + 内存默认实现
              （RLock 并发安全；仅单实例/测试使用，生产用 MySQL 审计表——只增，唯一自增主键，
              记录随业务量增长属规范预期，保留策略与流水表一致 ≥ 90 天）。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any, Protocol, runtime_checkable


@dataclass
class PaymentAuditRecord:
    """支付审计记录（一次支付动作一条，只增不改）"""

    action: str  # 动作（prepay/callback/book/refund/reversal/reconcile 等）
    out_trade_no: str = ""  # 商户订单号
    amount: str = ""  # 金额（字符串避免精度丢失，§8.1）
    channel: str = ""  # 渠道名
    result: str = ""  # 结果（success/failed/rejected 等，失败与异常同样留痕，§8.3）
    trace_id: str = ""  # 链路 TraceId（§8.3 全链路追溯）
    transaction_id: str = ""  # 渠道交易号
    operator: str = ""  # 操作人（人工对账/冲正时非空）
    detail: str = ""  # 补充说明（错误信息等，脱敏后）
    raw: dict = field(default_factory=dict)  # 渠道原始报文（§8.3 审计内容；§8.6 只落审计不落业务日志）
    audit_id: str = ""  # 审计记录号（缺省由存储生成）
    created_at: datetime | None = None  # 审计时间


@runtime_checkable
class PaymentAuditStoreInterface(Protocol):
    """支付审计存储抽象接口（业务按数据库实现，只增不改）"""

    async def append(self, record: PaymentAuditRecord, session: Any | None = None) -> PaymentAuditRecord:
        """写入审计记录（只增，不可覆盖删除；同 audit_id 幂等返回已有）"""
        ...


class InMemoryPaymentAuditStore:
    """内存支付审计存储（单实例/测试；生产用 MySQL 审计表）"""

    def __init__(self) -> None:
        self._records: list[PaymentAuditRecord] = []
        self._by_id: dict[str, PaymentAuditRecord] = {}
        self._lock = RLock()

    async def append(self, record: PaymentAuditRecord, session: Any | None = None) -> PaymentAuditRecord:
        """写入审计记录（只增不改；同 audit_id 幂等；RLock 并发安全）"""
        with self._lock:
            if not record.audit_id:
                record.audit_id = uuid.uuid4().hex
            if record.created_at is None:
                record.created_at = datetime.now()
            existing = self._by_id.get(record.audit_id)
            if existing is not None:
                return existing
            self._records.append(record)
            self._by_id[record.audit_id] = record
            return record

    async def list_all(self) -> list[PaymentAuditRecord]:
        """全部审计记录（测试/排查用）"""
        with self._lock:
            return list(self._records)
