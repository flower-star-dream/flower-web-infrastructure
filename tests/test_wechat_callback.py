"""
微信回调验签解密单元测试

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 覆盖回调验签（platform_cert/public_key 两种模式）、AES-256-GCM 报文解密、
              金额分→元换算、验签失败/时间戳超窗/缺头返回 None。
"""
import base64
import json
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from web_infra.payment.payment_constant import PaymentConstant
from web_infra.payment.payment_config import WechatPayConfig
from web_infra.payment.provider.wechat.wechat_callback_verifier import WeChatCallbackVerifier
from web_infra.payment.provider.wechat.wechat_signer import WeChatSigner

API_V3_KEY = "test-apiv3-key-0123456789abcdef0"  # 32 字节（AES-256-GCM 要求）


@pytest.fixture
def platform_key_pair() -> tuple[str, str]:
    """模拟微信支付平台密钥对（私钥签名回调 / 公钥验签）"""
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


def _encrypt_resource(plaintext: dict) -> dict:
    """按微信回调 resource 格式 AES-256-GCM 加密"""
    nonce = "0123456789ab"
    aad = "transaction"
    data = json.dumps(plaintext, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(API_V3_KEY.encode("utf-8")).encrypt(nonce.encode("utf-8"), data, aad.encode("utf-8"))
    return {
        "algorithm": "AEAD_AES_256_GCM",
        "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
        "nonce": nonce,
        "associated_data": aad,
    }


def _build_body(plaintext: dict) -> str:
    """构造回调 body（event_type + resource）"""
    return json.dumps({"event_type": plaintext["event_type"], "resource": _encrypt_resource(plaintext)}, ensure_ascii=False)


def _sign_headers(body: str, private_pem: str, serial: str, timestamp: str | None = None) -> dict:
    """用平台私钥签名 body 并构造回调头"""
    ts = timestamp or WeChatSigner.new_timestamp()
    nonce = "n-callback-1"
    signature = WeChatSigner.sign(private_pem, f"{ts}\n{nonce}\n{body}\n")
    return {
        "wechatpay-timestamp": ts,
        "wechatpay-nonce": nonce,
        "wechatpay-signature": signature,
        "wechatpay-serial": serial,
    }


def _pay_plaintext() -> dict:
    """支付成功回调明文（金额 100 分 = 1 元）"""
    return {
        "event_type": "TRANSACTION.SUCCESS",
        "out_trade_no": "T-20260816-001",
        "transaction_id": "4200001234",
        "attach": "biz-tag",
        "amount": {"total": 100, "payer_total": 100, "currency": "CNY"},
    }


def _refund_plaintext() -> dict:
    """退款成功回调明文（退款 50 分 = 0.5 元）"""
    return {
        "event_type": "REFUND.SUCCESS",
        "out_trade_no": "T-20260816-001",
        "transaction_id": "4200001234",
        "out_refund_no": "R-20260816-001",
        "refund_status": "SUCCESS",
        "amount": {"total": 100, "refund": 50, "payer_total": 100, "payer_refund": 50},
    }


@pytest.mark.asyncio
async def test_parse_pay_callback_with_platform_cert(tmp_path, platform_key_pair):
    """parse：platform_cert 模式验签+解密支付成功回调"""
    private_pem, public_pem = platform_key_pair
    serial = "PLATFORM-CERT-1"
    cert_file = tmp_path / f"{serial}.pem"
    cert_file.write_text(public_pem, encoding="utf-8")
    config = WechatPayConfig(api_v3_key=API_V3_KEY, verify_mode="platform_cert", platform_cert_dir=str(tmp_path))
    verifier = WeChatCallbackVerifier(config)

    plaintext = _pay_plaintext()
    body = _build_body(plaintext)
    headers = _sign_headers(body, private_pem, serial)

    callback = await verifier.parse(headers, body)
    assert callback is not None
    assert callback.event_type == "TRANSACTION.SUCCESS"
    assert callback.out_trade_no == "T-20260816-001"
    assert callback.transaction_id == "4200001234"
    assert callback.amount == Decimal("1.00")
    assert callback.attach == "biz-tag"


@pytest.mark.asyncio
async def test_parse_refund_callback_with_public_key(platform_key_pair):
    """parse：public_key 模式验签+解密退款成功回调"""
    private_pem, public_pem = platform_key_pair
    config = WechatPayConfig(api_v3_key=API_V3_KEY, verify_mode="public_key", public_key=public_pem)
    verifier = WeChatCallbackVerifier(config)

    plaintext = _refund_plaintext()
    body = _build_body(plaintext)
    headers = _sign_headers(body, private_pem, "PUBLIC-KEY-ID-1")

    callback = await verifier.parse(headers, body)
    assert callback is not None
    assert callback.event_type == "REFUND.SUCCESS"
    assert callback.mch_refund_no == "R-20260816-001"
    assert callback.refund_status.value == "SUCCESS"
    assert callback.amount == Decimal("0.50")


@pytest.mark.asyncio
async def test_parse_tampered_signature_returns_none(platform_key_pair):
    """parse：篡改签名返回 None"""
    private_pem, public_pem = platform_key_pair
    config = WechatPayConfig(api_v3_key=API_V3_KEY, verify_mode="public_key", public_key=public_pem)
    verifier = WeChatCallbackVerifier(config)

    body = _build_body(_pay_plaintext())
    headers = _sign_headers(body, private_pem, "PUBLIC-KEY-ID-1")
    headers["wechatpay-signature"] = "AAAA" + headers["wechatpay-signature"][4:]

    assert await verifier.parse(headers, body) is None


@pytest.mark.asyncio
async def test_parse_expired_timestamp_returns_none(platform_key_pair):
    """parse：时间戳超窗（>300s）返回 None"""
    private_pem, public_pem = platform_key_pair
    config = WechatPayConfig(api_v3_key=API_V3_KEY, verify_mode="public_key", public_key=public_pem)
    verifier = WeChatCallbackVerifier(config)

    body = _build_body(_pay_plaintext())
    headers = _sign_headers(body, private_pem, "PUBLIC-KEY-ID-1", timestamp=str(int(__import__("time").time()) - 3600))

    assert await verifier.parse(headers, body) is None


@pytest.mark.asyncio
async def test_parse_missing_headers_returns_none(platform_key_pair):
    """parse：缺少签名头返回 None"""
    _, public_pem = platform_key_pair
    config = WechatPayConfig(api_v3_key=API_V3_KEY, verify_mode="public_key", public_key=public_pem)
    verifier = WeChatCallbackVerifier(config)
    assert await verifier.parse({}, "{}") is None


@pytest.mark.asyncio
async def test_parse_unknown_serial_returns_none(tmp_path, platform_key_pair):
    """parse：platform_cert 模式无匹配序列号返回 None"""
    _, public_pem = platform_key_pair
    serial = "PLATFORM-CERT-1"
    (tmp_path / f"{serial}.pem").write_text(public_pem, encoding="utf-8")
    config = WechatPayConfig(api_v3_key=API_V3_KEY, verify_mode="platform_cert", platform_cert_dir=str(tmp_path))
    verifier = WeChatCallbackVerifier(config)

    body = _build_body(_pay_plaintext())
    headers = _sign_headers(body, platform_key_pair[0], "OTHER-SERIAL")

    assert await verifier.parse(headers, body) is None


def test_amount_scale_constant():
    """金额换算系数：分=元×100"""
    assert PaymentConstant.BIZ_PAY_AMOUNT_SCALE == 100
