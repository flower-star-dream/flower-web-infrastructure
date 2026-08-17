"""
支付订单查询结果模型

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 统一支付订单查询结果（对齐渠道交易状态与金额）。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from web_infra.payment.payment_status import PaymentStatus


class PaymentOrder(BaseModel):
    """支付订单查询结果"""

    out_trade_no: str = Field(description="商户订单号")
    transaction_id: str | None = Field(default=None, description="渠道交易号（未支付为 None）")
    status: PaymentStatus = Field(description="交易状态")
    total_amount: Decimal = Field(description="订单总金额（元）")
    payer_total: Decimal = Field(description="用户实付金额（元）")
    paid_at: datetime | None = Field(default=None, description="支付完成时间（未支付为 None）")
