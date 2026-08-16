"""
微信支付平台证书存储

@Author: 花海
@Date: 2026/08/16 11:00
@Description: 微信支付平台证书本地存储：解密下载接口返回的加密证书（AES-256-GCM，
              APIv3 密钥）、X509 证书提取公钥转 SPKI PEM、落盘 <序列号>.pem、
              下载成功后清理失效证书、按序列号加载。
              参考官方文档：下载平台证书 pay.weixin.qq.com/doc/v3/merchant/4012551764。
"""
from __future__ import annotations

import base64
import logging
import os

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from web_infra.payment.payment_config import WechatPayConfig

logger = logging.getLogger("web_infra.payment.wechat.certificate")


class WeChatCertificateStore:
    """微信支付平台证书本地存储（解密/公钥转换/落盘/清理/加载）"""

    def __init__(self, config: WechatPayConfig) -> None:
        self._config = config

    @staticmethod
    def decrypt_certificate(api_v3_key: str, resource: dict) -> str:
        """AES-256-GCM 解密证书内容（encrypt_certificate）得到 PEM 明文"""
        algorithm = resource.get("algorithm")
        if algorithm != "AEAD_AES_256_GCM":
            raise ValueError(f"不支持的加密算法：{algorithm}")
        ciphertext = base64.b64decode(resource["ciphertext"])
        nonce = resource["nonce"].encode("utf-8")
        aad = (resource.get("associated_data") or "").encode("utf-8")
        plaintext = AESGCM(api_v3_key.encode("utf-8")).decrypt(nonce, ciphertext, aad)
        return plaintext.decode("utf-8")

    @staticmethod
    def _to_public_key_pem(cert_pem: str) -> str:
        """X509 证书 PEM → SPKI 公钥 PEM（供验签使用）"""
        cert = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
        return cert.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    def persist_certificates(self, items: list[dict]) -> None:
        """解密平台证书列表并落盘 <序列号>.pem（公钥 PEM）；成功后清理 data 中不存在的旧证书

        :param items: /v3/certificates 响应 data 列表（每项含 serial_no / encrypt_certificate）
        """
        os.makedirs(self._config.platform_cert_dir, exist_ok=True)
        kept: set[str] = set()
        for item in items:
            serial_no = item.get("serial_no", "")
            if not serial_no:
                logger.warning("平台证书条目缺少 serial_no，跳过")
                continue
            cert_pem = self.decrypt_certificate(self._config.api_v3_key, item.get("encrypt_certificate") or {})
            public_key_pem = self._to_public_key_pem(cert_pem)
            path = os.path.join(self._config.platform_cert_dir, f"{serial_no}.pem")
            with open(path, "w", encoding="utf-8") as f:
                f.write(public_key_pem)
            kept.add(serial_no)
            logger.info("平台证书已更新 serial=%s", serial_no)
        # 清理本次列表外残留的旧证书（仅下载成功路径调用，下载失败不会走到这里，避免误删）
        if os.path.isdir(self._config.platform_cert_dir):
            for name in os.listdir(self._config.platform_cert_dir):
                if name.endswith(".pem") and name[:-4] not in kept:
                    os.remove(os.path.join(self._config.platform_cert_dir, name))
                    logger.info("平台证书已清理 serial=%s", name[:-4])

    def load(self, serial: str) -> str | None:
        """按序列号加载本地证书公钥 PEM；不存在返回 None"""
        path = os.path.join(self._config.platform_cert_dir, f"{serial}.pem")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
