"""
渠道账单统一交易明细（BillRecord）

@Author: 花海
@Date: 2026/08/17
@Description: 渠道账单解析后的统一交易明细（规范 §6.2/§2.2 对齐）：账单行字段收敛为
              订单号 + 事件类型 + 金额 + 状态 + 渠道交易号 + 账期，供对账服务与本地流水对齐。
              事件类型与本地流水事件（PaymentFlowEvent）对齐，金额统一 Decimal 元。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from web_infra.capabilities.payment.payment_flow_status import PaymentFlowEvent


@dataclass
class BillRecord:
    """渠道账单统一交易明细（对账对齐单元：订单号 + 事件类型 + 金额）"""

    out_trade_no: str  # 商户订单号（与本地流水/订单对齐键）
    event_type: PaymentFlowEvent  # 交易事件类型（PAY/REFUND/CLOSE）
    amount: Decimal  # 交易金额（元，支付=实付金额，退款=退款金额）
    transaction_id: str = ""  # 渠道交易号
    status: str = "SUCCESS"  # 账单状态（渠道口径：SUCCESS/CLOSED/PROCESSING 等）
    out_refund_no: str = ""  # 商户退款单号（退款账单非空）
    biz_date: date | None = None  # 账期（渠道账单归属日，T-1）
    raw: dict | None = None  # 账单原始行（审计，§8.3；对账日志不落原始明细，§8.6）
