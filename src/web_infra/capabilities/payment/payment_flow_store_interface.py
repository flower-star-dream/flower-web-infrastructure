"""
支付流水存储接口（SPI）

@Author: 花海
@Date: 2026/08/16
@Description: 支付流水本地事务表存储 SPI（规范 §5.2）：append 支持传入业务会话同事务写入
              （回调入账的本地事务：订单状态 + 流水 + 消息表同库原子提交，§5.1），
              以（out_trade_no + event_type）唯一索引兜底防重复入账（§4.3），
              重复 append 返回首次记录（回调幂等语义）。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from web_infra.capabilities.payment.payment_flow_record import PaymentFlowRecord
from web_infra.capabilities.payment.payment_flow_status import PaymentFlowEvent


@runtime_checkable
class PaymentFlowStoreInterface(Protocol):
    """支付流水存储抽象接口（业务按数据库实现，如 MySQL 本地事务表）"""

    async def append(self, record: PaymentFlowRecord, session: object | None = None) -> PaymentFlowRecord:
        """写入支付流水：默认自建会话提交；传 session 时与业务同事务提交（S21-1）。
        幂等语义（§4.3）：同（out_trade_no + event_type）已存在时返回已有记录，不重复写入。
        """
        ...

    async def find_by_order_and_event(self, out_trade_no: str, event_type: PaymentFlowEvent) -> PaymentFlowRecord | None:
        """按（订单号 + 事件类型）查流水（回调幂等/重复入账判定）"""
        ...

    async def find_by_flow_id(self, flow_id: str) -> PaymentFlowRecord | None:
        """按流水号查询"""
        ...

    async def find_reversal(self, original_flow_id: str) -> PaymentFlowRecord | None:
        """查原流水的冲正流水（§7.5 冲正幂等：原流水号 + 冲正唯一）"""
        ...

    async def sum_refunded(self, out_trade_no: str) -> Decimal:
        """按订单累计已退款金额（元，§5.3 部分退款累计约束：已退 + 本次 ≤ 实付）"""
        ...
