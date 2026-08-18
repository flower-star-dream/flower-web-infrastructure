"""
支付回调统一结构

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 统一支付/退款回调结构（验签解密后由渠道解析填充，业务处理器消费）。
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from web_infra.capabilities.payment.payment_status import RefundStatus


class PaymentCallback(BaseModel):
    """支付/退款回调统一结构"""

    event_type: str = Field(description="回调事件类型（TRANSACTION.SUCCESS / REFUND.SUCCESS 等）")
    out_trade_no: str = Field(description="商户订单号")
    transaction_id: str | None = Field(default=None, description="渠道交易号（退款通知也为原支付交易号）")
    amount: Decimal = Field(description="回调金额（元；支付=实付金额，退款=退款金额）")
    refund_status: RefundStatus | None = Field(default=None, description="退款状态（退款类回调非空）")
    mch_refund_no: str | None = Field(default=None, description="商户退款单号（退款类回调非空）")
    attach: str | None = Field(default=None, description="下单时的商户附加数据")
    raw: dict = Field(default_factory=dict, description="渠道原始明文（审计/排障）")
