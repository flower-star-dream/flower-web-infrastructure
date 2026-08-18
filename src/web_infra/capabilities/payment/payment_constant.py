"""
支付业务常量类

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 支付域业务常量（金额元→分换算系数、币种标识、回调事件类型），
              对齐 Java 侧 PaymentConstant。
"""
from __future__ import annotations


class PaymentConstant:
    """支付业务常量（金额换算、币种、回调事件类型）"""

    # 金额元→分换算系数（微信支付金额单位为分）
    BIZ_PAY_AMOUNT_SCALE = 100

    # 人民币币种标识
    BIZ_PAY_CURRENCY_CNY = "CNY"

    # 回调事件类型（微信支付通知 event_type）
    EVENT_PAY_SUCCESS = "TRANSACTION.SUCCESS"
    EVENT_REFUND_SUCCESS = "REFUND.SUCCESS"
    EVENT_REFUND_ABNORMAL = "REFUND.ABNORMAL"
    EVENT_REFUND_CLOSED = "REFUND.CLOSED"

    # 回调签名时间戳最大容差（秒，防重放）
    CALLBACK_SIGN_EXPIRE_SECONDS = 300
