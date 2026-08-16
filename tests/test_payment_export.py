"""
支付模块导出冒烟测试

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 覆盖 web_infra 顶层与 payment 子模块的关键导出。
"""
from web_infra import (
    PaymentCallback,
    PaymentCallbackDispatcher,
    PaymentGateway,
    PaymentPrepayRequest,
)
from web_infra.payment import (
    InMemoryPaymentGateway,
    PaymentGatewayRegistry,
    PaymentScene,
    PaymentStatus,
    WechatPayConfig,
)


def test_top_level_exports():
    """web_infra 顶层导出支付核心类"""
    assert PaymentGateway is not None
    assert PaymentCallback is not None
    assert PaymentCallbackDispatcher is not None
    assert PaymentPrepayRequest is not None


def test_payment_submodule_exports():
    """payment 子模块导出"""
    assert InMemoryPaymentGateway is not None
    assert PaymentGatewayRegistry is not None
    assert PaymentScene.JSAPI.value == "JSAPI"
    assert PaymentStatus.SUCCESS.value == "SUCCESS"
    assert WechatPayConfig is not None
