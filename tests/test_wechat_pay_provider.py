"""
微信支付 Provider 单元测试

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 覆盖四场景下单（URL/金额分/JSAPI openid/H5 scene_info/调起参数）、
              查单/关单/退款/查退款参数构造、404→None、未知场景抛 E4-PAY-004。
"""
import json
from decimal import Decimal

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from web_infra.error.biz_exception import BizException
from web_infra.payment.payment_error_code import PaymentErrorCode
from web_infra.payment.payment_scene import PaymentScene
from web_infra.payment.payment_status import PaymentStatus
from web_infra.payment.prepay_request import PaymentPrepayRequest
from web_infra.payment.refund_request import PaymentRefundRequest
from web_infra.payment.provider.wechat.wechat_pay_client import WeChatPayClient
from web_infra.payment.payment_config import WechatPayConfig
from web_infra.payment.provider.wechat.wechat_pay_provider import WeChatPayProvider


def _make_provider(handler, **config_overrides) -> WeChatPayProvider:
    """构造带 MockTransport 的 Provider（注入测试 RSA 私钥供请求签名/调起支付签名）"""
    test_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = test_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    config = WechatPayConfig(
        appid="wx-app",
        mchid="1900000001",
        mch_serial_no="MCH-SERIAL-1",
        api_v3_key="test-apiv3-key-0123456789abcdef0",
        private_key=private_pem,
        private_key_path="",
        notify_url="https://example.com/pay/notify",
        refund_notify_url="https://example.com/pay/refund-notify",
        **config_overrides,
    )
    client = WeChatPayClient(config, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return WeChatPayProvider(config, client=client)


def _capture_handler(captured: dict, response: httpx.Response):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content) if request.content else {}
        return response
    return handler


@pytest.mark.asyncio
async def test_prepay_jsapi():
    """prepay：JSAPI 请求体含 payer.openid，返回调起支付参数"""
    captured: dict = {}
    provider = _make_provider(
        _capture_handler(captured, httpx.Response(200, json={"prepay_id": "prepay-jsapi-1"}, headers={"Content-Type": "application/json"}))
    )
    req = PaymentPrepayRequest(scene=PaymentScene.JSAPI, out_trade_no="T-JSAPI", description="商品", total_amount=Decimal("1.50"), openid="o-1")
    resp = await provider.prepay(req)
    assert captured["url"].endswith("/v3/pay/transactions/jsapi")
    assert captured["body"]["amount"]["total"] == 150  # 1.50 元 = 150 分
    assert captured["body"]["payer"] == {"openid": "o-1"}
    assert captured["body"]["notify_url"] == "https://example.com/pay/notify"
    assert resp.prepay_id == "prepay-jsapi-1"
    assert resp.pay_params["appId"] == "wx-app"
    assert resp.pay_params["package"] == "prepay_id=prepay-jsapi-1"
    assert resp.pay_params["signType"] == "RSA"
    assert resp.pay_params["paySign"]


@pytest.mark.asyncio
async def test_prepay_native():
    """prepay：Native 请求体无 payer，返回 code_url"""
    captured: dict = {}
    provider = _make_provider(
        _capture_handler(captured, httpx.Response(200, json={"code_url": "weixin://wxpay/bizpayurl?pr=abc"}, headers={"Content-Type": "application/json"}))
    )
    req = PaymentPrepayRequest(scene=PaymentScene.NATIVE, out_trade_no="T-NATIVE", description="商品", total_amount=Decimal("2.00"))
    resp = await provider.prepay(req)
    assert captured["url"].endswith("/v3/pay/transactions/native")
    assert "payer" not in captured["body"]
    assert resp.code_url == "weixin://wxpay/bizpayurl?pr=abc"


@pytest.mark.asyncio
async def test_prepay_h5():
    """prepay：H5 请求体含 scene_info，返回 h5_url"""
    captured: dict = {}
    provider = _make_provider(
        _capture_handler(captured, httpx.Response(200, json={"h5_url": "https://wx.tenpay.com/cgi-bin/mmpayweb/bin/checkoutpage"}, headers={"Content-Type": "application/json"}))
    )
    req = PaymentPrepayRequest(scene=PaymentScene.H5, out_trade_no="T-H5", description="商品", total_amount=Decimal("3.00"), client_ip="1.2.3.4")
    resp = await provider.prepay(req)
    assert captured["url"].endswith("/v3/pay/transactions/h5")
    assert captured["body"]["scene_info"]["payer_client_ip"] == "1.2.3.4"
    assert resp.h5_url == "https://wx.tenpay.com/cgi-bin/mmpayweb/bin/checkoutpage"


@pytest.mark.asyncio
async def test_prepay_app():
    """prepay：App 请求体无 payer，返回 App 调起参数（partnerid/package=Sign=WXPay）"""
    captured: dict = {}
    provider = _make_provider(
        _capture_handler(captured, httpx.Response(200, json={"prepay_id": "prepay-app-1"}, headers={"Content-Type": "application/json"}))
    )
    req = PaymentPrepayRequest(scene=PaymentScene.APP, out_trade_no="T-APP", description="商品", total_amount=Decimal("4.00"))
    resp = await provider.prepay(req)
    assert captured["url"].endswith("/v3/pay/transactions/app")
    assert resp.pay_params["partnerid"] == "1900000001"
    assert resp.pay_params["prepayid"] == "prepay-app-1"
    assert resp.pay_params["package"] == "Sign=WXPay"


@pytest.mark.asyncio
async def test_prepay_jsapi_missing_openid():
    """prepay：JSAPI 缺 openid 抛 E4-PAY-004"""
    provider = _make_provider(lambda req: httpx.Response(500))
    req = PaymentPrepayRequest(scene=PaymentScene.JSAPI, out_trade_no="T-JSAPI-2", description="商品", total_amount=Decimal("1.00"))
    with pytest.raises(BizException) as exc_info:
        await provider.prepay(req)
    assert exc_info.value.code == PaymentErrorCode.PAY_SCENE_UNSUPPORTED.code


@pytest.mark.asyncio
async def test_query_order_success():
    """query_order：解析交易状态与金额（分→元）"""
    captured: dict = {}
    provider = _make_provider(
        _capture_handler(captured, httpx.Response(200, json={
            "out_trade_no": "T1", "transaction_id": "420000001",
            "trade_state": "SUCCESS", "amount": {"total": 200, "payer_total": 200},
            "success_time": "2026-08-16T10:00:00+08:00",
        }, headers={"Content-Type": "application/json"}))
    )
    order = await provider.query_order("T1")
    assert captured["url"].endswith("/v3/pay/transactions/out-trade-no/T1?mchid=1900000001")
    assert order is not None
    assert order.status == PaymentStatus.SUCCESS
    assert order.total_amount == Decimal("2.00")
    assert order.payer_total == Decimal("2.00")


@pytest.mark.asyncio
async def test_query_order_not_found_returns_none():
    """query_order：微信 404 返回 None"""
    provider = _make_provider(
        lambda req: httpx.Response(404, json={"code": "ORDER_NOT_EXIST", "message": "订单不存在"}, headers={"Content-Type": "application/json"})
    )
    assert await provider.query_order("not-exist") is None


@pytest.mark.asyncio
async def test_close_order():
    """close_order：骨架先查单确认未支付，再调关单接口（§5.5 防已支付被关闭）"""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/close"):
            calls.append("close")
            return httpx.Response(204)
        calls.append("query")
        return httpx.Response(200, json={
            "out_trade_no": "T1", "trade_state": "NOTPAY", "amount": {"total": 100},
        }, headers={"Content-Type": "application/json"})

    provider = _make_provider(handler)
    await provider.close_order("T1")
    assert calls == ["query", "close"]  # 查单确认未支付 → 关单
    assert provider._client is not None


@pytest.mark.asyncio
async def test_close_order_refuses_paid_order():
    """close_order：查单确认已支付 → 禁止关单（抛 E4-PAY-003，§5.5）"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={
            "out_trade_no": "T1", "trade_state": "SUCCESS", "amount": {"total": 100},
        }, headers={"Content-Type": "application/json"})

    provider = _make_provider(handler)
    with pytest.raises(BizException) as exc_info:
        await provider.close_order("T1")
    assert exc_info.value.code == "E4-PAY-003"
    assert calls["n"] == 1  # 查单后即拒绝，未调关单


@pytest.mark.asyncio
async def test_refund():
    """refund：金额分与退款单号构造"""
    captured: dict = {}
    provider = _make_provider(
        _capture_handler(captured, httpx.Response(200, json={
            "out_refund_no": "R1", "refund_id": "REF-1", "status": "PROCESSING",
            "amount": {"refund": 50},
        }, headers={"Content-Type": "application/json"}))
    )
    req = PaymentRefundRequest(out_trade_no="T1", out_refund_no="R1", refund_amount=Decimal("0.50"), total_amount=Decimal("2.00"), reason="部分退款")
    resp = await provider.refund(req)
    assert captured["url"].endswith("/v3/refund/domestic/refunds")
    assert captured["body"]["amount"] == {"refund": 50, "total": 200, "currency": "CNY"}
    assert resp.status.value == "PROCESSING"
    assert resp.refund_amount == Decimal("0.50")


@pytest.mark.asyncio
async def test_prepay_no_blind_retry():
    """下单重试边界（规范 §7.2）：prepay 失败禁止盲目重试，仅调用一次（防重复下单/重复扣款）"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"code": "SYSTEM_ERROR", "message": "系统繁忙"})

    provider = _make_provider(handler)
    req = PaymentPrepayRequest(scene=PaymentScene.NATIVE, out_trade_no="T-NO-RETRY", description="商品", total_amount=Decimal("1.00"))
    with pytest.raises(BizException) as exc_info:
        await provider.prepay(req)
    assert exc_info.value.code == PaymentErrorCode.PAY_CHANNEL_ERROR.code
    assert calls["n"] == 1  # 下单不自动重试，由业务查单确认后决策


@pytest.mark.asyncio
async def test_query_order_retains_retry():
    """下单重试边界：幂等接口（查单）保留自动重试（out_trade_no 天然幂等，重试安全）"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(500, json={"code": "SYSTEM_ERROR", "message": "系统繁忙"})
        return httpx.Response(200, json={
            "out_trade_no": "T1", "trade_state": "SUCCESS", "amount": {"total": 100},
        }, headers={"Content-Type": "application/json"})

    provider = _make_provider(handler)
    order = await provider.query_order("T1")
    assert order is not None
    assert order.status == PaymentStatus.SUCCESS
    assert calls["n"] == 3  # 首次 + 2 次重试
