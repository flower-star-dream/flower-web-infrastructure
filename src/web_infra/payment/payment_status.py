"""
支付与退款状态枚举

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 支付订单交易状态与退款状态枚举（对齐微信支付 APIv3 状态值）。
"""
from __future__ import annotations

from enum import Enum


class PaymentStatus(str, Enum):
    """支付订单交易状态枚举"""

    SUCCESS = "SUCCESS"
    REFUND = "REFUND"
    NOTPAY = "NOTPAY"
    CLOSED = "CLOSED"
    REVOKED = "REVOKED"
    PAYERROR = "PAYERROR"
    USERPAYING = "USERPAYING"


class RefundStatus(str, Enum):
    """退款状态枚举"""

    SUCCESS = "SUCCESS"
    CLOSED = "CLOSED"
    PROCESSING = "PROCESSING"
    ABNORMAL = "ABNORMAL"
