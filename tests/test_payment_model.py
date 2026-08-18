"""
支付数据模型单元测试

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 覆盖支付请求/响应/回调模型的字段约束（场景枚举、金额 Decimal、gt=0 校验）。
"""
from decimal import Decimal

import pytest
from pydantic import ValidationError

from web_infra.capabilities.payment.payment_callback import PaymentCallback
from web_infra.capabilities.payment.payment_order import PaymentOrder
from web_infra.capabilities.payment.payment_scene import PaymentScene
from web_infra.capabilities.payment.payment_status import PaymentStatus, RefundStatus
from web_infra.capabilities.payment.prepay_request import PaymentPrepayRequest
from web_infra.capabilities.payment.prepay_response import PaymentPrepayResponse
from web_infra.capabilities.payment.refund_request import PaymentRefundRequest
from web_infra.capabilities.payment.refund_response import PaymentRefundResponse


def test_prepay_request_minimal():
    """PaymentPrepayRequest：最小必填字段构造"""
    req = PaymentPrepayRequest(scene=PaymentScene.NATIVE, out_trade_no="T20260816001", description="测试商品", total_amount=Decimal("1.00"))
    assert req.scene == PaymentScene.NATIVE
    assert req.total_amount == Decimal("1.00")
    assert req.notify_url is None
    assert req.attach is None


def test_prepay_request_invalid_scene():
    """PaymentPrepayRequest：非法场景值触发 ValidationError"""
    with pytest.raises(ValidationError):
        PaymentPrepayRequest(scene="ALIPAY", out_trade_no="T1", description="x", total_amount=Decimal("1.00"))


def test_prepay_request_zero_amount_rejected():
    """PaymentPrepayRequest：金额不大于 0 触发 ValidationError"""
    with pytest.raises(ValidationError):
        PaymentPrepayRequest(scene=PaymentScene.JSAPI, out_trade_no="T1", description="x", total_amount=Decimal("0.00"))


def test_prepay_response_scene_fields():
    """PaymentPrepayResponse：各场景字段独立"""
    native = PaymentPrepayResponse(scene=PaymentScene.NATIVE, code_url="weixin://pay/x")
    assert native.prepay_id is None
    assert native.h5_url is None
    jsapi = PaymentPrepayResponse(scene=PaymentScene.JSAPI, prepay_id="prepay-1", pay_params={"prepay_id": "prepay-1"})
    assert jsapi.code_url is None


def test_refund_request_positive_amount():
    """PaymentRefundRequest：退款/原单金额必须大于 0"""
    with pytest.raises(ValidationError):
        PaymentRefundRequest(out_trade_no="T1", out_refund_no="R1", refund_amount=Decimal("0"), total_amount=Decimal("1.00"))


def test_callback_model():
    """PaymentCallback：退款回调字段填充"""
    cb = PaymentCallback(
        event_type="REFUND.SUCCESS",
        out_trade_no="T1",
        mch_refund_no="R1",
        amount=Decimal("0.50"),
        refund_status=RefundStatus.SUCCESS,
    )
    assert cb.refund_status == RefundStatus.SUCCESS
    assert cb.raw == {}


def test_order_model_status_enum():
    """PaymentOrder：状态字段枚举化"""
    order = PaymentOrder(out_trade_no="T1", status=PaymentStatus.SUCCESS, total_amount=Decimal("1.00"), payer_total=Decimal("1.00"))
    assert order.status == PaymentStatus.SUCCESS
