"""
退款请求模型

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 统一退款请求结构（金额 Decimal 元，out_refund_no 为退款幂等键）。
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class PaymentRefundRequest(BaseModel):
    """退款请求"""

    out_trade_no: str = Field(description="商户订单号")
    out_refund_no: str = Field(description="商户退款单号（渠道侧唯一，退款幂等键）")
    refund_amount: Decimal = Field(gt=0, description="退款金额（元，必须大于 0）")
    total_amount: Decimal = Field(gt=0, description="原订单总金额（元）")
    reason: str | None = Field(default=None, description="退款原因")
    refund_notify_url: str | None = Field(default=None, description="退款结果回调地址（缺省用渠道配置）")
