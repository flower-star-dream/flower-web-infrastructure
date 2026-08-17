"""
支付网关 SPI 契约测试（内存默认实现）

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 以 InMemoryPaymentGateway 验证 PaymentGateway 契约：四场景下单、
              查单 None 语义、关单状态流转、退款与查退款。
"""
from decimal import Decimal

import pytest

from web_infra.payment.in_memory_payment_gateway import InMemoryPaymentGateway
from web_infra.payment.payment_order import PaymentOrder
from web_infra.payment.payment_scene import PaymentScene
from web_infra.payment.payment_status import PaymentStatus, RefundStatus
from web_infra.payment.prepay_request import PaymentPrepayRequest
from web_infra.payment.refund_request import PaymentRefundRequest


@pytest.fixture
def gateway() -> InMemoryPaymentGateway:
    return InMemoryPaymentGateway()


@pytest.mark.asyncio
async def test_prepay_jsapi_returns_pay_params(gateway):
    """prepay：JSAPI 返回 prepay_id 与调起参数"""
    req = PaymentPrepayRequest(scene=PaymentScene.JSAPI, out_trade_no="T1", description="x", total_amount=Decimal("1.00"), openid="o-1")
    resp = await gateway.prepay(req)
    assert resp.prepay_id == "prepay-T1"
    assert resp.pay_params == {"prepay_id": "prepay-T1"}
    assert resp.code_url is None
    assert resp.h5_url is None


@pytest.mark.asyncio
async def test_prepay_native_returns_code_url(gateway):
    """prepay：Native 返回二维码内容"""
    req = PaymentPrepayRequest(scene=PaymentScene.NATIVE, out_trade_no="T2", description="x", total_amount=Decimal("1.00"))
    resp = await gateway.prepay(req)
    assert resp.code_url == "weixin://pay/prepay-T2"


@pytest.mark.asyncio
async def test_prepay_h5_returns_h5_url(gateway):
    """prepay：H5 返回跳转链接"""
    req = PaymentPrepayRequest(scene=PaymentScene.H5, out_trade_no="T3", description="x", total_amount=Decimal("1.00"), client_ip="1.2.3.4")
    resp = await gateway.prepay(req)
    assert resp.h5_url == "https://example.com/pay/prepay-T3"


@pytest.mark.asyncio
async def test_query_order_unknown_returns_none(gateway):
    """query_order：未下单订单返回 None"""
    assert await gateway.query_order("not-exist") is None


@pytest.mark.asyncio
async def test_close_order_marks_closed(gateway):
    """close_order：关闭后查单状态为 CLOSED"""
    req = PaymentPrepayRequest(scene=PaymentScene.APP, out_trade_no="T4", description="x", total_amount=Decimal("2.00"))
    await gateway.prepay(req)
    await gateway.close_order("T4")
    order = await gateway.query_order("T4")
    assert order is not None and order.status == PaymentStatus.CLOSED


@pytest.mark.asyncio
async def test_refund_roundtrip(gateway):
    """refund/query_refund：退款后按退款单号可查"""
    await gateway.prepay(PaymentPrepayRequest(scene=PaymentScene.NATIVE, out_trade_no="T5", description="x", total_amount=Decimal("3.00")))
    req = PaymentRefundRequest(out_trade_no="T5", out_refund_no="R5", refund_amount=Decimal("1.00"), total_amount=Decimal("3.00"))
    resp = await gateway.refund(req)
    assert resp.status == RefundStatus.SUCCESS
    queried = await gateway.query_refund("R5")
    assert queried is not None and queried.out_refund_no == "R5"


@pytest.mark.asyncio
async def test_seed_order_supports_success_scenario(gateway):
    """seed_order：测试辅助注入已支付订单，验证契约可模拟支付成功"""
    gateway.seed_order(PaymentOrder(out_trade_no="T6", status=PaymentStatus.SUCCESS, total_amount=Decimal("1.00"), payer_total=Decimal("1.00")))
    order = await gateway.query_order("T6")
    assert order is not None and order.status == PaymentStatus.SUCCESS
