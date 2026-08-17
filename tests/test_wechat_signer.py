"""
微信签名器单元测试

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 覆盖商户请求签名（SHA256withRSA）、应答/回调验签、Authorization 头
              与 JSAPI/App 调起支付签名串构造。
"""
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from web_infra.payment.provider.wechat.wechat_signer import WeChatSigner


@pytest.fixture
def rsa_key_pair() -> tuple[str, str]:
    """生成测试 RSA 密钥对（私钥 PEM / 公钥 PEM）"""
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


def test_sign_verify_roundtrip(rsa_key_pair):
    """sign/verify：同一密钥对往返通过"""
    private_pem, public_pem = rsa_key_pair
    signature = WeChatSigner.sign(private_pem, "message-1")
    assert WeChatSigner.verify(public_pem, "message-1", signature) is True


def test_verify_tampered_message_fails(rsa_key_pair):
    """verify：篡改消息验签失败"""
    private_pem, public_pem = rsa_key_pair
    signature = WeChatSigner.sign(private_pem, "message-1")
    assert WeChatSigner.verify(public_pem, "message-2", signature) is False
    assert WeChatSigner.verify(public_pem, "message-1", "bad-signature") is False


def test_request_signature_message_format(rsa_key_pair):
    """request_signature：签名串为 method\nurl\nts\nnonce\nbody\n"""
    private_pem, _ = rsa_key_pair
    sign = WeChatSigner.request_signature("POST", "/v3/pay/transactions/jsapi", "{}", private_pem, timestamp="1700000000", nonce="n-1")
    expected_message = "POST\n/v3/pay/transactions/jsapi\n1700000000\nn-1\n{}\n"
    assert sign["timestamp"] == "1700000000"
    assert sign["nonce"] == "n-1"
    assert WeChatSigner.verify(rsa_key_pair[1], expected_message, sign["signature"]) is True


def test_authorization_header_format():
    """authorization_header：WECHATPAY2-SHA256-RSA2048 头格式"""
    header = WeChatSigner.authorization_header("mch-1", "serial-1", "1700000000", "n-1", "sig-1")
    assert header.startswith("WECHATPAY2-SHA256-RSA2048 mchid=")
    assert 'mchid="mch-1"' in header
    assert 'serial_no="serial-1"' in header
    assert 'timestamp="1700000000"' in header


def test_verify_response(rsa_key_pair):
    """verify_response：应答验签（timestamp\nnonce\nbody\n）"""
    private_pem, public_pem = rsa_key_pair
    body = '{"out_trade_no":"T1"}'
    signature = WeChatSigner.sign(private_pem, f"1700000000\nn-1\n{body}\n")
    assert WeChatSigner.verify_response("1700000000", "n-1", body, signature, public_pem) is True


def test_jsapi_pay_sign_message(rsa_key_pair):
    """jsapi 调起支付签名串：appId\nts\nnonce\npackage\nRSA"""
    private_pem, public_pem = rsa_key_pair
    message = "\n".join(["wx-app", "1700000000", "n-1", "prepay_id=p-1", "RSA"])
    signature = WeChatSigner.jsapi_pay_sign("wx-app", "1700000000", "n-1", "p-1", private_pem)
    assert WeChatSigner.verify(public_pem, message, signature) is True


def test_app_pay_sign_message(rsa_key_pair):
    """app 调起支付签名串：appId\nts\nnonce\nprepay_id=xxx"""
    private_pem, public_pem = rsa_key_pair
    message = "\n".join(["wx-app", "1700000000", "n-1", "prepay_id=p-1"])
    signature = WeChatSigner.app_pay_sign("wx-app", "1700000000", "n-1", "p-1", private_pem)
    assert WeChatSigner.verify(public_pem, message, signature) is True
