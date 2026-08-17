"""
支付错误码单元测试

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 覆盖支付错误码定义、注册表登记与 to_exception 抛出。
"""
import pytest

from web_infra.error.error_code_registry import ErrorCodeRegistry
from web_infra.error.biz_exception import BizException
from web_infra.payment.payment_error_code import PaymentErrorCode, PaymentErrorCodeEnum


def test_enum_members():
    """PaymentErrorCodeEnum：渠道类可重试，业务类不可重试"""
    assert PaymentErrorCodeEnum.PAY_CHANNEL_ERROR.value.code == "E3-PAY-000"
    assert PaymentErrorCodeEnum.PAY_CHANNEL_ERROR.value.retryable is True
    assert PaymentErrorCodeEnum.PAY_SIGN_VERIFY_FAILED.value.code == "E3-PAY-001"
    assert PaymentErrorCodeEnum.PAY_NOT_CONFIGURED.value.code == "E4-PAY-001"
    assert PaymentErrorCodeEnum.PAY_NOT_CONFIGURED.value.retryable is False


def test_class_attributes_reference_enum():
    """PaymentErrorCode：类属性引用枚举成员值"""
    assert PaymentErrorCode.PAY_CHANNEL_ERROR.code == "E3-PAY-000"
    assert PaymentErrorCode.PAY_AMOUNT_MISMATCH.code == "E4-PAY-002"
    assert PaymentErrorCode.PAY_SCENE_UNSUPPORTED.code == "E4-PAY-004"


def test_registered_in_registry():
    """注册表：支付错误码已登记且可反查"""
    assert ErrorCodeRegistry.get("E3-PAY-000").code == "E3-PAY-000"
    assert PaymentErrorCodeEnum.of("E4-PAY-003") is not None
    assert PaymentErrorCodeEnum.of("E9-XXX-000") is None


def test_to_exception():
    """to_exception：抛出携带错误码的 BizException"""
    exc = PaymentErrorCode.PAY_CHANNEL_ERROR.to_exception(message="微信支付超时")
    assert isinstance(exc, BizException)
    assert exc.code == "E3-PAY-000"


def test_http_status():
    """HTTP 状态：E3-PAY 渠道 502，E4-PAY 业务 422/409"""
    assert PaymentErrorCode.PAY_CHANNEL_ERROR.http_status == 502
    assert PaymentErrorCode.PAY_ORDER_STATE_CONFLICT.http_status == 409
