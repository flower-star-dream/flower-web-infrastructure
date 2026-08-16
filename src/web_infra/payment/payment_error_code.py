"""
支付错误码

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 支付错误码定义（规范 §4）：渠道调用类 E3-PAY（可重试）、业务状态类 E4-PAY。
              权威定义见 PaymentErrorCodeEnum，PaymentErrorCode 类属性引用枚举成员值。
"""
from __future__ import annotations

import logging
from enum import Enum

from web_infra.error.error_code import ErrorCode
from web_infra.error.error_code_registry import ErrorCodeRegistry


class PaymentErrorCodeEnum(Enum):
    """支付错误码枚举（规范 §4：渠道类 E3 可重试 / 业务类 E4 不可重试）"""

    # E3-PAY 渠道调用（可重试）
    PAY_CHANNEL_ERROR = ErrorCode("E3-PAY-000", "支付渠道调用失败", 502, "E3", retryable=True, log_level=logging.ERROR)
    PAY_SIGN_VERIFY_FAILED = ErrorCode("E3-PAY-001", "回调验签失败/报文解密失败", 401, "E3", log_level=logging.ERROR)

    # E4-PAY 业务状态（不可重试）
    PAY_NOT_CONFIGURED = ErrorCode("E4-PAY-001", "支付渠道未配置/未注册", 422, "E4", log_level=logging.WARNING)
    PAY_AMOUNT_MISMATCH = ErrorCode("E4-PAY-002", "回调金额与订单不符", 422, "E4", log_level=logging.WARNING)
    PAY_ORDER_STATE_CONFLICT = ErrorCode("E4-PAY-003", "订单状态冲突（重复回调/已关闭）", 409, "E4", log_level=logging.WARNING)
    PAY_SCENE_UNSUPPORTED = ErrorCode("E4-PAY-004", "支付场景不支持", 422, "E4", log_level=logging.WARNING)

    @classmethod
    def of(cls, code: str) -> "PaymentErrorCodeEnum | None":
        """按 code 反查枚举成员；未找到返回 None"""
        for member in cls:
            if member.value.code == code:
                return member
        return None


class PaymentErrorCode:
    """支付错误码（属性引用枚举成员值，对外 API 兼容）"""

    PAY_CHANNEL_ERROR = PaymentErrorCodeEnum.PAY_CHANNEL_ERROR.value
    PAY_SIGN_VERIFY_FAILED = PaymentErrorCodeEnum.PAY_SIGN_VERIFY_FAILED.value
    PAY_NOT_CONFIGURED = PaymentErrorCodeEnum.PAY_NOT_CONFIGURED.value
    PAY_AMOUNT_MISMATCH = PaymentErrorCodeEnum.PAY_AMOUNT_MISMATCH.value
    PAY_ORDER_STATE_CONFLICT = PaymentErrorCodeEnum.PAY_ORDER_STATE_CONFLICT.value
    PAY_SCENE_UNSUPPORTED = PaymentErrorCodeEnum.PAY_SCENE_UNSUPPORTED.value


def _register_payment_codes() -> None:
    """将支付错误码登记到注册表（模块导入时执行一次）"""
    for member in PaymentErrorCodeEnum:
        ErrorCodeRegistry.register(member.value)


_register_payment_codes()
