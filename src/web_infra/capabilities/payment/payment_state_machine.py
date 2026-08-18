"""
支付状态机

@Author: 花海
@Date: 2026/08/16
@Description: 支付订单状态机（规范 §4.5 权威状态定义）：合法流转校验表 + 幂等重复判定。
              终态（SUCCESS/CLOSED/REVOKED/REFUND）不可回退；EXCEPTION 为异常挂账态（非终态）
              仅由对账收敛（RECONCILE_*）；同一状态收到同事件（重复回调）按幂等成功返回原状态，
              其余非法流转抛 E4-PAY-003（状态冲突）。
"""
from __future__ import annotations

from web_infra.capabilities.payment.payment_error_code import PaymentErrorCode
from web_infra.capabilities.payment.payment_status import PaymentEvent, PaymentStatus


class PaymentStateMachine:
    """支付状态机：合法流转校验 + 幂等重复判定（业务与骨架共用权威定义，禁止各模块自定义）"""

    # 合法流转表（规范 §4.5）：当前状态 -> {事件: 目标状态}
    _TRANSITIONS: dict[PaymentStatus, dict[PaymentEvent, PaymentStatus]] = {
        PaymentStatus.NOTPAY: {
            PaymentEvent.PAY_SUCCESS: PaymentStatus.SUCCESS,
            PaymentEvent.PAY_FAILED: PaymentStatus.PAYERROR,
            PaymentEvent.PAY_TIMEOUT: PaymentStatus.CLOSED,
            PaymentEvent.CLOSE: PaymentStatus.CLOSED,
        },
        PaymentStatus.USERPAYING: {
            PaymentEvent.PAY_SUCCESS: PaymentStatus.SUCCESS,
            PaymentEvent.PAY_FAILED: PaymentStatus.PAYERROR,
            PaymentEvent.CONFIRM_FAILED: PaymentStatus.CLOSED,
            PaymentEvent.CONFIRM_EXCEED: PaymentStatus.EXCEPTION,
        },
        PaymentStatus.EXCEPTION: {
            PaymentEvent.RECONCILE_SUCCESS: PaymentStatus.SUCCESS,
            PaymentEvent.RECONCILE_FAILED: PaymentStatus.CLOSED,
        },
        PaymentStatus.SUCCESS: {
            PaymentEvent.REFUND_SUCCESS: PaymentStatus.REFUND,
            PaymentEvent.REFUND_PARTIAL: PaymentStatus.SUCCESS,
        },
    }

    # 幂等重复对（§4.3）：同一状态收到同一事件 → 幂等成功返回原状态，非冲突
    _IDEMPOTENT_PAIRS: frozenset[tuple[PaymentStatus, PaymentEvent]] = frozenset({
        (PaymentStatus.SUCCESS, PaymentEvent.PAY_SUCCESS),
        (PaymentStatus.SUCCESS, PaymentEvent.REFUND_PARTIAL),
        (PaymentStatus.REFUND, PaymentEvent.REFUND_SUCCESS),
        (PaymentStatus.CLOSED, PaymentEvent.CLOSE),
    })

    @classmethod
    def target(cls, current: PaymentStatus, event: PaymentEvent) -> PaymentStatus:
        """按合法流转表求目标状态（幂等重复返回原状态；非法抛 E4-PAY-003）"""
        if (current, event) in cls._IDEMPOTENT_PAIRS:
            return current
        targets = cls._TRANSITIONS.get(current)
        if targets is None or event not in targets:
            raise PaymentErrorCode.PAY_ORDER_STATE_CONFLICT.to_exception(
                message=f"非法支付状态流转: {current.value} + {event.value}（规范 §4.5）"
            )
        return targets[event]

    @classmethod
    def is_idempotent_repeat(cls, current: PaymentStatus, event: PaymentEvent) -> bool:
        """是否为幂等重复事件（重复回调/重复通知返回首次结果，§4.3）"""
        return (current, event) in cls._IDEMPOTENT_PAIRS

    @classmethod
    def is_terminal(cls, status: PaymentStatus) -> bool:
        """是否终态（§4.5：SUCCESS/CLOSED/REVOKED/REFUND 不可回退；EXCEPTION 非终态）"""
        return status in {
            PaymentStatus.SUCCESS,
            PaymentStatus.CLOSED,
            PaymentStatus.REVOKED,
            PaymentStatus.REFUND,
        }
