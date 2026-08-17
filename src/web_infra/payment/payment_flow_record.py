"""
支付流水记录模型

@Author: 花海
@Date: 2026/08/16
@Description: 支付流水本地明细（规范 §5.2）：承载全部资金变更（支付成功/退款成功/冲正/关单），
              是对账（§6）与审计（§8.3）的本地权威依据。
              幂等域：唯一索引（out_trade_no + event_type）兜底防重复入账（§4.3）；
              冲正域：original_flow_id / is_reversal 支撑 §7.5 冲正"新增反向流水 + 标记原流水"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from web_infra.payment.payment_flow_status import PaymentFlowEvent, PaymentFlowStatus


@dataclass
class PaymentFlowRecord:
    """支付流水记录（本地资金变更明细）"""

    out_trade_no: str  # 商户订单号
    event_type: PaymentFlowEvent  # 事件类型（幂等域：订单号 + 事件类型唯一）
    amount: Decimal  # 本次资金变更金额（元）
    status: PaymentFlowStatus = PaymentFlowStatus.BOOKED  # 本地账务状态
    flow_id: str = ""  # 流水号（缺省由存储生成）
    out_refund_no: str = ""  # 商户退款单号（退款/冲正流水非空）
    original_flow_id: str = ""  # 冲正域：原流水号（冲正流水填写）
    is_reversal: bool = False  # 冲正域：是否冲正流水（§7.5）
    reversed_at: datetime | None = None  # 冲正域：冲正时间
    currency: str = "CNY"  # 币种
    channel: str = ""  # 渠道名
    transaction_id: str = ""  # 渠道交易号
    raw: dict = field(default_factory=dict)  # 渠道原始报文（审计，§8.3）
    created_at: datetime | None = None  # 创建时间
    callback_at: datetime | None = None  # 回调到达时间
    cleaned_at: datetime | None = None  # 清理时间（§4.4 保留期策略）
