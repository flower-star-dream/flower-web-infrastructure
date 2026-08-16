"""
微信支付 HTTP 客户端单元测试

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 覆盖请求签名头自动附加、微信业务错误映射 E3-PAY-000、
              404 且 not_found_ok 返回 None、204 返回空字典。
"""
import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from web_infra.error.biz_exception import BizException
from web_infra.payment.payment_error_code import PaymentErrorCode
from web_infra.payment.provider.wechat.wechat_pay_client import WeChatPayClient
from web_infra.payment.payment_config import WechatPayConfig
from web_infra.payment.provider.wechat.wechat_signer import WeChatSigner


@pytest.fixture
def merchant_keys() -> tuple[str, str]:
    """商户侧密钥对（私钥签名请求）"""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


@pytest.fixture
def config(merchant_keys) -> WechatPayConfig:
    return WechatPayConfig(
        appid="wx-app",
        mchid="1900000001",
        mch_serial_no="MCH-SERIAL-1",
        api_v3_key="test-apiv3-key-0123456789abcdef0",
        private_key=merchant_keys[0],
        verify_mode="public_key",
        public_key="",  # 应答验签用例单独注入平台公钥
    )


@pytest.mark.asyncio
async def test_request_adds_authorization_header(config):
    """request：自动附加 Authorization 签名头（含 mchid/serial_no）"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(200, text="{}", headers={"Content-Type": "application/json"})

    client = WeChatPayClient(config, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = await client.request("POST", "/v3/pay/transactions/jsapi", {"out_trade_no": "T1"})
    assert result == {}
    assert 'mchid="1900000001"' in captured["auth"]
    assert 'serial_no="MCH-SERIAL-1"' in captured["auth"]
    assert captured["auth"].startswith("WECHATPAY2-SHA256-RSA2048 ")


@pytest.mark.asyncio
async def test_request_wechat_error_maps_to_channel_error(config):
    """request：微信返回业务错误映射为 E3-PAY-000"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": "PARAM_ERROR", "message": "参数错误"}, headers={"Content-Type": "application/json"})

    client = WeChatPayClient(config, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(BizException) as exc_info:
        await client.request("POST", "/v3/pay/transactions/jsapi", {})
    assert exc_info.value.code == PaymentErrorCode.PAY_CHANNEL_ERROR.code


@pytest.mark.asyncio
async def test_request_404_not_found_ok_returns_none(config):
    """request：404 且 not_found_ok=True 返回 None"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": "ORDER_NOT_EXIST", "message": "订单不存在"}, headers={"Content-Type": "application/json"})

    client = WeChatPayClient(config, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await client.request("GET", "/v3/pay/transactions/out-trade-no/xxx?mchid=1", not_found_ok=True) is None


@pytest.mark.asyncio
async def test_request_204_returns_empty_dict(config):
    """request：204 返回空字典（关闭订单）"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    client = WeChatPayClient(config, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await client.request("POST", "/v3/pay/transactions/out-trade-no/xxx/close", {"mchid": "1"}) == {}


@pytest.mark.asyncio
async def test_request_verifies_response_signature(config, merchant_keys):
    """request：带微信应答签名头时验签；伪造签名抛 E3-PAY-000"""
    _, merchant_public = merchant_keys
    platform_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    platform_private_pem = platform_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    platform_public_pem = platform_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    def build_response(body: str) -> httpx.Response:
        ts = WeChatSigner.new_timestamp()
        nonce = "n-resp-1"
        signature = WeChatSigner.sign(platform_private_pem, f"{ts}\n{nonce}\n{body}\n")
        return httpx.Response(
            200, text=body,
            headers={
                "Wechatpay-Timestamp": ts,
                "Wechatpay-Nonce": nonce,
                "Wechatpay-Signature": signature,
                "Wechatpay-Serial": "PLAT-1",
                "Content-Type": "application/json",
            },
        )

    ok_body = '{"out_trade_no":"T1"}'

    def good_handler(request: httpx.Request) -> httpx.Response:
        return build_response(ok_body)

    # 验签通过：注入平台公钥
    cfg_ok = config.model_copy(update={"public_key": platform_public_pem})
    client_ok = WeChatPayClient(cfg_ok, http_client=httpx.AsyncClient(transport=httpx.MockTransport(good_handler)))
    data = await client_ok.request("GET", "/v3/pay/transactions/out-trade-no/T1?mchid=1")
    assert data == {"out_trade_no": "T1"}

    # 伪造签名：验签失败
    cfg_bad = config.model_copy(update={"public_key": merchant_public})
    client_bad = WeChatPayClient(cfg_bad, http_client=httpx.AsyncClient(transport=httpx.MockTransport(good_handler)))
    with pytest.raises(BizException) as exc_info:
        await client_bad.request("GET", "/v3/pay/transactions/out-trade-no/T1?mchid=1")
    assert exc_info.value.code == PaymentErrorCode.PAY_CHANNEL_ERROR.code
