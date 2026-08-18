"""
内存支付流水存储

@Author: 花海
@Date: 2026/08/16
@Description: PaymentFlowStoreInterface 内存默认实现（单实例/测试；生产用 MySQL 本地事务表）。
              （out_trade_no + event_type）唯一键 + RLock 保证幂等（重复 append 返回首次记录，§4.3）。
"""
from __future__ import annotations

import uuid
from threading import RLock
from typing import Any

from web_infra.capabilities.payment.payment_flow_record import PaymentFlowRecord
from web_infra.capabilities.payment.payment_flow_status import PaymentFlowEvent, PaymentFlowStatus


class InMemoryPaymentFlowStore:
    """内存支付流水存储（默认实现）"""

    def __init__(self) -> None:
        self._flows: dict[str, PaymentFlowRecord] = {}  # flow_id -> record
        self._by_key: dict[tuple[str, str], PaymentFlowRecord] = {}  # (out_trade_no, event_type) -> record
        self._lock = RLock()

    async def append(self, record: PaymentFlowRecord, session: Any | None = None) -> PaymentFlowRecord:
        """写入流水（幂等：同订单号 + 事件类型已存在返回首次记录，不重复写入）。
        冲正内聚（§7.5）：写入冲正流水（is_reversal）时自动标记原流水为 REVERSED + 冲正时间。"""
        with self._lock:
            key = (record.out_trade_no, record.event_type.value)
            existing = self._by_key.get(key)
            if existing is not None:
                return existing
            if not record.flow_id:
                record.flow_id = uuid.uuid4().hex
            if record.created_at is None:
                from datetime import datetime, timezone

                record.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
            # 冲正内聚（§7.5）：原流水标记为已冲正（新增反向流水 + 标记原流水，不可删除）
            if record.is_reversal and record.original_flow_id:
                original = self._flows.get(record.original_flow_id)
                if original is not None:
                    original.status = PaymentFlowStatus.REVERSED
                    original.reversed_at = record.reversed_at
            self._flows[record.flow_id] = record
            self._by_key[key] = record
            return record

    async def find_by_order_and_event(self, out_trade_no: str, event_type: PaymentFlowEvent) -> PaymentFlowRecord | None:
        """按（订单号 + 事件类型）查流水"""
        with self._lock:
            return self._by_key.get((out_trade_no, event_type.value))

    async def find_by_flow_id(self, flow_id: str) -> PaymentFlowRecord | None:
        """按流水号查询"""
        with self._lock:
            return self._flows.get(flow_id)

    async def find_reversal(self, original_flow_id: str) -> PaymentFlowRecord | None:
        """查原流水的冲正流水（§7.5 冲正幂等）"""
        with self._lock:
            return next((f for f in self._flows.values() if f.is_reversal and f.original_flow_id == original_flow_id), None)

    async def sum_refunded(self, out_trade_no: str) -> Any:
        """按订单累计已退款金额（元，§5.3 部分退款累计约束）"""
        from decimal import Decimal

        with self._lock:
            total = Decimal("0")
            for flow in self._flows.values():
                if flow.out_trade_no == out_trade_no and flow.event_type == PaymentFlowEvent.REFUND and flow.is_reversal is False:
                    total += flow.amount
            return total
