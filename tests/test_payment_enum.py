"""
支付枚举与常量单元测试

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 覆盖支付场景/状态枚举取值与支付常量定义。
"""
from web_infra.capabilities.payment.payment_constant import PaymentConstant
from web_infra.capabilities.payment.payment_scene import PaymentScene
from web_infra.capabilities.payment.payment_status import PaymentStatus, RefundStatus


def test_payment_scene_values():
    """PaymentScene：四场景取值与枚举顺序"""
    assert PaymentScene.JSAPI.value == "JSAPI"
    assert PaymentScene.NATIVE.value == "NATIVE"
    assert PaymentScene.H5.value == "H5"
    assert PaymentScene.APP.value == "APP"
    assert list(PaymentScene) == [PaymentScene.JSAPI, PaymentScene.NATIVE, PaymentScene.H5, PaymentScene.APP]


def test_payment_status_values():
    """PaymentStatus：交易状态取值"""
    assert PaymentStatus.SUCCESS.value == "SUCCESS"
    assert PaymentStatus.NOTPAY.value == "NOTPAY"
    assert PaymentStatus.USERPAYING.value == "USERPAYING"
    assert PaymentStatus.CLOSED.value == "CLOSED"


def test_refund_status_values():
    """RefundStatus：退款状态取值"""
    assert RefundStatus.SUCCESS.value == "SUCCESS"
    assert RefundStatus.CLOSED.value == "CLOSED"
    assert RefundStatus.PROCESSING.value == "PROCESSING"
    assert RefundStatus.ABNORMAL.value == "ABNORMAL"


def test_payment_constant():
    """PaymentConstant：金额系数/币种/回调事件类型"""
    assert PaymentConstant.BIZ_PAY_AMOUNT_SCALE == 100
    assert PaymentConstant.BIZ_PAY_CURRENCY_CNY == "CNY"
    assert PaymentConstant.EVENT_PAY_SUCCESS == "TRANSACTION.SUCCESS"
    assert PaymentConstant.EVENT_REFUND_SUCCESS == "REFUND.SUCCESS"
