"""
微信支付回调验签解密器

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 微信支付回调验签 + AES-256-GCM 报文解密（实现 PaymentCallbackVerifier SPI）。
              验签失败/解密失败/解析失败统一返回 None（调用方返回 401，微信自动重试）。
              参考官方文档：回调报文解密 pay.weixin.qq.com/doc/v3/merchant/4012071382。
              平台证书自动下载：注入 WeChatPayClient 且 cert_auto_download 开启时，
              验签遇未知序列号自动调用 /v3/certificates 获取并缓存。
"""
from __future__ import annotations

import base64
import json
import logging
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Mapping

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from web_infra.capabilities.payment.payment_callback import PaymentCallback
from web_infra.capabilities.payment.payment_callback_verifier_interface import PaymentCallbackVerifier
from web_infra.capabilities.payment.payment_config import WechatPayConfig
from web_infra.capabilities.payment.payment_constant import PaymentConstant
from web_infra.capabilities.payment.provider.wechat.wechat_signer import WeChatSigner

if TYPE_CHECKING:
    from web_infra.capabilities.payment.provider.wechat.wechat_pay_client import WeChatPayClient

logger = logging.getLogger("web_infra.capabilities.payment.wechat.callback")


class WeChatCallbackVerifier(PaymentCallbackVerifier):
    """微信支付回调验签解密器（platform_cert / public_key 两种验签模式）"""

    HEADER_TIMESTAMP = "wechatpay-timestamp"
    HEADER_NONCE = "wechatpay-nonce"
    HEADER_SIGNATURE = "wechatpay-signature"
    HEADER_SERIAL = "wechatpay-serial"

    def __init__(self, config: WechatPayConfig, client: "WeChatPayClient | None" = None) -> None:
        self._config = config
        self._client = client

    async def parse(self, headers: Mapping[str, str], body: str) -> PaymentCallback | None:
        timestamp = headers.get(self.HEADER_TIMESTAMP, "")
        nonce = headers.get(self.HEADER_NONCE, "")
        signature = headers.get(self.HEADER_SIGNATURE, "")
        serial = headers.get(self.HEADER_SERIAL, "")
        if not all([timestamp, nonce, signature, serial]):
            logger.warning("微信回调缺少签名头，拒绝")
            return None
        if not self._timestamp_in_window(timestamp):
            logger.warning("微信回调时间戳超窗，拒绝")
            return None
        public_key = self._config.load_verify_key(serial)
        if public_key is None and self._client is not None and self._config.verify_mode == "platform_cert" and self._config.cert_auto_download:
            logger.info("回调验签未知平台证书序列号 serial=%s，触发自动下载", serial)
            await self._client.download_certificates()
            public_key = self._config.load_verify_key(serial)
        if public_key is None:
            logger.warning("微信回调无匹配验签凭据 serial=%s", serial)
            return None
        message = f"{timestamp}\n{nonce}\n{body}\n"
        if not WeChatSigner.verify(public_key, message, signature):
            logger.warning("微信回调验签失败 serial=%s", serial)
            return None
        try:
            payload = json.loads(body)
            plaintext = self._decrypt_resource(payload.get("resource") or {})
            return self._to_callback(plaintext)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.error("微信回调报文解密/解析失败：%s", exc)
            return None

    def _timestamp_in_window(self, timestamp: str) -> bool:
        """时间戳容差校验（防重放）"""
        try:
            return abs(int(timestamp) - int(time.time())) <= PaymentConstant.CALLBACK_SIGN_EXPIRE_SECONDS
        except ValueError:
            return False

    def _decrypt_resource(self, resource: dict) -> dict:
        """AES-256-GCM 解密 resource 得到明文 JSON"""
        algorithm = resource.get("algorithm")
        if algorithm != "AEAD_AES_256_GCM":
            raise ValueError(f"不支持的加密算法：{algorithm}")
        ciphertext = base64.b64decode(resource["ciphertext"])
        nonce = resource["nonce"].encode("utf-8")
        aad = (resource.get("associated_data") or "").encode("utf-8")
        key = self._config.api_v3_key.encode("utf-8")
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad)
        return json.loads(plaintext.decode("utf-8"))

    def _to_callback(self, plaintext: dict) -> PaymentCallback:
        """明文映射为统一回调结构（金额分→元）"""
        amount_obj = plaintext.get("amount") or {}
        is_refund = "refund_status" in plaintext or "out_refund_no" in plaintext
        if is_refund:
            amount_fen = amount_obj.get("payer_refund") or amount_obj.get("refund") or 0
        else:
            amount_fen = amount_obj.get("payer_total") or amount_obj.get("total") or 0
        return PaymentCallback(
            event_type=plaintext.get("event_type", ""),
            out_trade_no=plaintext.get("out_trade_no", ""),
            transaction_id=plaintext.get("transaction_id"),
            amount=Decimal(amount_fen) / Decimal(PaymentConstant.BIZ_PAY_AMOUNT_SCALE),
            refund_status=plaintext.get("refund_status"),
            mch_refund_no=plaintext.get("out_refund_no"),
            attach=plaintext.get("attach"),
            raw=plaintext,
        )
