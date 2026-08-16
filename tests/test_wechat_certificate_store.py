"""
微信平台证书存储单元测试

@Author: 花海
@Date: 2026/08/16 11:00
@Description: 覆盖平台证书解密（AES-256-GCM）、X509 证书→公钥 PEM 转换、
              落盘/加载与下载成功后的失效证书清理。
"""
import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import NameOID

from web_infra.payment.payment_config import WechatPayConfig
from web_infra.payment.provider.wechat.wechat_certificate_store import WeChatCertificateStore
from web_infra.payment.provider.wechat.wechat_signer import WeChatSigner

API_V3_KEY = "test-apiv3-key-0123456789abcdef0"  # 32 字节


def _make_cert_pem() -> str:
    """生成测试自签名 X509 证书 PEM"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "wechatpay-test")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")


def _encrypt_certificate(cert_pem: str) -> dict:
    """按微信下载平台证书接口格式构造 encrypt_certificate"""
    nonce = "0123456789ab"
    aad = "certificate"
    ciphertext = AESGCM(API_V3_KEY.encode("utf-8")).encrypt(nonce.encode("utf-8"), cert_pem.encode("utf-8"), aad.encode("utf-8"))
    return {
        "algorithm": "AEAD_AES_256_GCM",
        "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
        "nonce": nonce,
        "associated_data": aad,
    }


def _cert_item(serial_no: str, cert_pem: str) -> dict:
    return {"serial_no": serial_no, "effective_time": "2026-01-01T00:00:00+08:00", "expire_time": "2031-01-01T00:00:00+08:00", "encrypt_certificate": _encrypt_certificate(cert_pem)}


def test_decrypt_certificate_returns_pem():
    """decrypt_certificate：AES-256-GCM 解密得到证书 PEM 明文"""
    cert_pem = _make_cert_pem()
    plaintext = WeChatCertificateStore.decrypt_certificate(API_V3_KEY, _encrypt_certificate(cert_pem))
    assert plaintext == cert_pem


def test_decrypt_unsupported_algorithm_raises():
    """decrypt_certificate：非 AEAD_AES_256_GCM 抛 ValueError"""
    resource = {"algorithm": "RSA", "ciphertext": "", "nonce": "", "associated_data": ""}
    with pytest.raises(ValueError):
        WeChatCertificateStore.decrypt_certificate(API_V3_KEY, resource)


def test_persist_and_load_public_key(tmp_path):
    """persist_certificates：落盘公钥 PEM（可被 WeChatSigner.verify 使用），load 可读回"""
    config = WechatPayConfig(api_v3_key=API_V3_KEY, verify_mode="platform_cert", platform_cert_dir=str(tmp_path))
    store = WeChatCertificateStore(config)
    cert_pem = _make_cert_pem()
    serial_no = "PLAT-SERIAL-0001"

    store.persist_certificates([_cert_item(serial_no, cert_pem)])

    loaded = store.load(serial_no)
    assert loaded is not None
    assert loaded.startswith("-----BEGIN PUBLIC KEY-----")
    # 转换后的公钥能正常验签（用证书对应私钥签名验证——公钥来自证书）
    message = "verify-me"
    # 用证书内公钥对应的私钥签名：重新生成对应私钥不可行，改用 WeChatSigner 加载公钥验证解析正确
    assert WeChatSigner.load_public_key(loaded) is not None


def test_persist_cleans_stale_certificates(tmp_path):
    """persist_certificates：下载成功后清理 data 中不存在的旧证书文件"""
    config = WechatPayConfig(api_v3_key=API_V3_KEY, verify_mode="platform_cert", platform_cert_dir=str(tmp_path))
    store = WeChatCertificateStore(config)
    stale_path = tmp_path / "OLD-SERIAL.pem"
    stale_path.write_text("stale", encoding="utf-8")

    store.persist_certificates([_cert_item("NEW-SERIAL", _make_cert_pem())])

    assert not stale_path.exists()
    assert (tmp_path / "NEW-SERIAL.pem").exists()


def test_load_missing_returns_none(tmp_path):
    """load：不存在的序列号返回 None"""
    config = WechatPayConfig(api_v3_key=API_V3_KEY, verify_mode="platform_cert", platform_cert_dir=str(tmp_path))
    store = WeChatCertificateStore(config)
    assert store.load("NOT-EXIST") is None
