"""
支付网关注册表单元测试

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 覆盖渠道注册/查询/注销与未注册渠道异常。
"""
import pytest

from web_infra.payment.in_memory_payment_gateway import InMemoryPaymentGateway
from web_infra.payment.payment_error_code import PaymentErrorCode
from web_infra.payment.payment_gateway_registry import PaymentGatewayRegistry


@pytest.mark.asyncio
async def test_register_and_get():
    """register/get：注册后可查询到渠道实例"""
    name = "test-memory-1"
    gateway = InMemoryPaymentGateway()
    PaymentGatewayRegistry.register(name, gateway)
    try:
        assert PaymentGatewayRegistry.get(name) is gateway
        assert name in PaymentGatewayRegistry.registered_names()
    finally:
        PaymentGatewayRegistry.unregister(name)


def test_get_unregistered_raises():
    """get：未注册渠道抛 E4-PAY-001"""
    with pytest.raises(Exception) as exc_info:
        PaymentGatewayRegistry.get("not-registered")
    assert getattr(exc_info.value, "code", "") == PaymentErrorCode.PAY_NOT_CONFIGURED.code


def test_unregister_missing_no_error():
    """unregister：注销未注册渠道不抛错"""
    PaymentGatewayRegistry.unregister("ghost")
