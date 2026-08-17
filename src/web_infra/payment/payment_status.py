"""
支付与退款状态枚举

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 支付订单交易状态与退款状态枚举（对齐微信支付 APIv3 状态值）。
"""
from __future__ import annotations

from enum import Enum


class PaymentStatus(str, Enum):
    """支付订单交易状态枚举（对齐微信支付 APIv3 状态值 + 规范 §4.5 完整状态机）"""

    SUCCESS = "SUCCESS"
    REFUND = "REFUND"
    NOTPAY = "NOTPAY"
    CLOSED = "CLOSED"
    REVOKED = "REVOKED"
    PAYERROR = "PAYERROR"
    USERPAYING = "USERPAYING"
    EXCEPTION = "EXCEPTION"  # 异常挂账态（非终态）：结果未知超窗口后强制挂账，由对账收敛（规范 §4.5/§7.4）


class PaymentEvent(str, Enum):
    """支付状态机事件（规范 §4.5：支付/退款/关单/对账收敛）"""

    PAY_SUCCESS = "pay_success"        # 用户支付成功（回调/查单确认）
    PAY_FAILED = "pay_failed"          # 渠道明确返回支付失败
    PAY_TIMEOUT = "pay_timeout"        # 订单超时（定时关单）
    CLOSE = "close"                    # 用户取消/重新下单关单
    CONFIRM_FAILED = "confirm_failed"  # 查单确认未支付/超时 → 关单
    CONFIRM_EXCEED = "confirm_exceed"  # 查证超过最大窗口 → 强制挂账 EXCEPTION
    RECONCILE_SUCCESS = "reconcile_success"  # 对账确认渠道已收款 → 补入账
    RECONCILE_FAILED = "reconcile_failed"    # 对账确认渠道未收款 → 冲正关闭
    REFUND_SUCCESS = "refund_success"  # 全额退款成功 → REFUND
    REFUND_PARTIAL = "refund_partial"  # 部分退款 → 保持 SUCCESS


class RefundStatus(str, Enum):
    """退款状态枚举"""

    SUCCESS = "SUCCESS"
    CLOSED = "CLOSED"
    PROCESSING = "PROCESSING"
    ABNORMAL = "ABNORMAL"
