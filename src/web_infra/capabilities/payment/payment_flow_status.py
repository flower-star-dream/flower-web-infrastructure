"""
支付流水本地账务状态枚举

@Author: 花海
@Date: 2026/08/16
@Description: 支付流水本地账务状态（规范 §5.2 状态域）：入账/待入账/冲正/已关闭，
              与支付订单状态（PaymentStatus）分离——流水承载资金变更明细，账务状态标识入账进度。
"""
from __future__ import annotations

from enum import Enum


class PaymentFlowStatus(str, Enum):
    """支付流水本地账务状态"""

    BOOKED = "BOOKED"        # 已入账（资金已确认入账）
    PENDING = "PENDING"      # 待入账（结果未知/待查证，规范 §7.4）
    REVERSED = "REVERSED"    # 已冲正（新增反向冲正流水标记原流水，§7.5）
    CLOSED = "CLOSED"        # 已关闭（关单流水记录订单关闭事实，§5.5）


class PaymentFlowEvent(str, Enum):
    """支付流水事件类型（规范 §5.2 幂等域：唯一索引 = 订单号 + 事件类型）"""

    PAY = "PAY"              # 支付成功入账
    REFUND = "REFUND"        # 退款成功入账
    CLOSE = "CLOSE"          # 关单
    REVERSAL = "REVERSAL"    # 冲正
