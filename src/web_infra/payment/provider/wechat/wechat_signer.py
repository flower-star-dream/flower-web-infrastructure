"""
微信支付签名工具

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 微信支付 APIv3 签名工具：商户请求签名（SHA256withRSA）、应答/回调验签、
              授权头构造、JSAPI/App 调起支付签名。参考微信支付官方文档
              （APIv3 总述-签名验签：pay.weixin.qq.com/doc/v3/merchant/4012365342）。
              密钥 PEM 解析结果按内容进程内缓存（P1 优化：高频下单/验签避免重复解析 RSA）。
"""
from __future__ import annotations

import base64
import functools
import time
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class WeChatSigner:
    """微信支付 APIv3 签名工具（商户私钥签名 + 平台证书/公钥验签）"""

    @staticmethod
    @functools.lru_cache(maxsize=8)
    def load_private_key(private_key_pem: str):
        """加载商户 API 私钥（PKCS8 PEM；解析结果按内容缓存，密钥轮换换内容自动换缓存）"""
        return serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)

    @staticmethod
    @functools.lru_cache(maxsize=8)
    def load_public_key(public_key_pem: str):
        """加载验签公钥（微信支付公钥或平台证书内公钥，SPKI PEM；解析结果按内容缓存）"""
        return serialization.load_pem_public_key(public_key_pem.encode("utf-8"))

    @staticmethod
    def new_timestamp() -> str:
        """当前 Unix 时间戳（秒，字符串）"""
        return str(int(time.time()))

    @staticmethod
    def new_nonce() -> str:
        """随机 nonce（32 位十六进制串）"""
        return str(uuid.uuid4()).replace("-", "")

    @staticmethod
    def sign(private_key_pem: str, message: str) -> str:
        """SHA256withRSA 签名，返回 base64 签名"""
        private_key = WeChatSigner.load_private_key(private_key_pem)
        signature = private_key.sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        return base64.b64encode(signature).decode("utf-8")

    @staticmethod
    def verify(public_key_pem: str, message: str, signature: str) -> bool:
        """用平台公钥验签（SHA256withRSA）；失败返回 False"""
        try:
            public_key = WeChatSigner.load_public_key(public_key_pem)
            public_key.verify(
                base64.b64decode(signature),
                message.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            return True
        except (InvalidSignature, ValueError):
            return False

    @staticmethod
    def request_signature(method: str, canonical_url: str, body: str, private_key_pem: str,
                          timestamp: str | None = None, nonce: str | None = None) -> dict:
        """构造请求签名要素：签名串 method\nurl\nts\nnonce\nbody\n"""
        ts = timestamp or WeChatSigner.new_timestamp()
        n = nonce or WeChatSigner.new_nonce()
        message = f"{method}\n{canonical_url}\n{ts}\n{n}\n{body}\n"
        return {"timestamp": ts, "nonce": n, "signature": WeChatSigner.sign(private_key_pem, message)}

    @staticmethod
    def authorization_header(mchid: str, serial_no: str, timestamp: str, nonce: str, signature: str) -> str:
        """构造 Authorization 请求头（WECHATPAY2-SHA256-RSA2048）"""
        return (
            f'WECHATPAY2-SHA256-RSA2048 mchid="{mchid}",nonce_str="{nonce}",'
            f'signature="{signature}",timestamp="{timestamp}",serial_no="{serial_no}"'
        )

    @staticmethod
    def verify_response(timestamp: str, nonce: str, body: str, signature: str, platform_public_key_pem: str) -> bool:
        """应答/回调验签：签名串 timestamp\nnonce\nbody\n"""
        message = f"{timestamp}\n{nonce}\n{body}\n"
        return WeChatSigner.verify(platform_public_key_pem, message, signature)

    @staticmethod
    def jsapi_pay_sign(appid: str, timestamp: str, nonce: str, prepay_id: str, private_key_pem: str) -> str:
        """JSAPI/小程序调起支付签名：appId\nts\nnonce\npackage\nsignType"""
        message = "\n".join([appid, timestamp, nonce, f"prepay_id={prepay_id}", "RSA"])
        return WeChatSigner.sign(private_key_pem, message)

    @staticmethod
    def app_pay_sign(appid: str, timestamp: str, nonce: str, prepay_id: str, private_key_pem: str) -> str:
        """App 调起支付签名：appId\nts\nnonce\nprepay_id=xxx"""
        message = "\n".join([appid, timestamp, nonce, f"prepay_id={prepay_id}"])
        return WeChatSigner.sign(private_key_pem, message)
