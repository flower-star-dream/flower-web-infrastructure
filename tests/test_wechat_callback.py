"""
微信回调验签解密单元测试

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 覆盖回调验签（platform_cert/public_key 两种模式）、AES-256-GCM 报文解密、
              金额分→元换算、验签失败/时间戳超窗/缺头返回 None、平台证书自动下载。
"""
import base64
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import NameOID

from web_infra.payment.payment_constant import PaymentConstant
from web_infra.payment.payment_config import WechatPayConfig
from web_infra.payment.provider.wechat.wechat_callback_verifier import WeChatCallbackVerifier
from web_infra.payment.provider.wechat.wechat_pay_client import WeChatPayClient
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


# ---------------------------------------------------------------------------
# 平台证书自动下载
# ---------------------------------------------------------------------------


def _make_cert_pem(public_pem: str) -> str:
    """用指定公钥 PEM 生成自签名 X509 证书"""
    public_key = serialization.load_pem_public_key(public_pem.encode("utf-8"))
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "wechatpay-test")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .sign(rsa.generate_private_key(public_exponent=65537, key_size=2048), hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")


def _cert_item(serial_no: str, cert_pem: str) -> dict:
    """构造下载平台证书接口返回的 data 列表项（APIv3 密钥加密）"""
    nonce = "0123456789ab"
    aad = "certificate"
    ciphertext = AESGCM(API_V3_KEY.encode("utf-8")).encrypt(nonce.encode("utf-8"), cert_pem.encode("utf-8"), aad.encode("utf-8"))
    return {
        "serial_no": serial_no,
        "effective_time": "2026-01-01T00:00:00+08:00",
        "expire_time": "2031-01-01T00:00:00+08:00",
        "encrypt_certificate": {"algorithm": "AEAD_AES_256_GCM", "ciphertext": base64.b64encode(ciphertext).decode("utf-8"), "nonce": nonce, "associated_data": aad},
    }


@pytest.mark.asyncio
async def test_parse_auto_download_platform_cert(tmp_path, platform_key_pair):
    """parse：platform_cert + cert_auto_download + 注入 client：未知序列号自动下载后验签通过"""
    private_pem, public_pem = platform_key_pair
    serial = "AUTO-SERIAL-0001"
    cert_pem = _make_cert_pem(public_pem)
    merchant_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    merchant_private_pem = merchant_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/certificates"
        return httpx.Response(200, json={"data": [_cert_item(serial, cert_pem)]}, headers={"Content-Type": "application/json"})

    config = WechatPayConfig(api_v3_key=API_V3_KEY, verify_mode="platform_cert", platform_cert_dir=str(tmp_path),
                             cert_auto_download=True, private_key=merchant_private_pem)
    client = WeChatPayClient(config, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    verifier = WeChatCallbackVerifier(config, client=client)

    body = _build_body(_pay_plaintext())
    headers = _sign_headers(body, private_pem, serial)

    callback = await verifier.parse(headers, body)
    assert callback is not None
    assert callback.out_trade_no == "T-20260816-001"
    assert callback.amount == Decimal("1.00")


@pytest.mark.asyncio
async def test_parse_auto_download_disabled_returns_none(tmp_path, platform_key_pair):
    """parse：cert_auto_download 关闭且本地无证书：不触发下载，返回 None"""
    private_pem, public_pem = platform_key_pair
    serial = "AUTO-SERIAL-0002"

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("不应触发平台证书下载")

    config = WechatPayConfig(api_v3_key=API_V3_KEY, verify_mode="platform_cert", platform_cert_dir=str(tmp_path), cert_auto_download=False)
    client = WeChatPayClient(config, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    verifier = WeChatCallbackVerifier(config, client=client)

    body = _build_body(_pay_plaintext())
    headers = _sign_headers(body, private_pem, serial)

    assert await verifier.parse(headers, body) is None


@pytest.mark.asyncio
async def test_parse_auto_download_without_client_returns_none(tmp_path, platform_key_pair):
    """parse：未注入 client：即使开启自动下载也不下载，返回 None"""
    private_pem, _ = platform_key_pair
    serial = "AUTO-SERIAL-0003"
    config = WechatPayConfig(api_v3_key=API_V3_KEY, verify_mode="platform_cert", platform_cert_dir=str(tmp_path), cert_auto_download=True)
    verifier = WeChatCallbackVerifier(config)  # 不注入 client

    body = _build_body(_pay_plaintext())
    headers = _sign_headers(body, private_pem, serial)

    assert await verifier.parse(headers, body) is None
