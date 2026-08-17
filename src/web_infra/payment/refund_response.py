"""
退款结果模型

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 统一退款结果（对齐渠道退款状态与金额）。
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from web_infra.payment.payment_status import RefundStatus


class PaymentRefundResponse(BaseModel):
    """退款结果"""

    out_refund_no: str = Field(description="商户退款单号")
    refund_id: str | None = Field(default=None, description="渠道退款单号（处理中可能为空）")
    status: RefundStatus = Field(description="退款状态")
    refund_amount: Decimal = Field(description="退款金额（元）")
