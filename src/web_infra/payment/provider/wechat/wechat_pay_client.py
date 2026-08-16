"""
微信支付 APIv3 HTTP 客户端

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 微信支付 APIv3 请求客户端：自动附加请求签名头、应答验签、错误码映射。
              底层 httpx，可注入 transport 供测试（httpx.MockTransport）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from web_infra.payment.payment_error_code import PaymentErrorCode
from web_infra.payment.payment_config import WechatPayConfig
from web_infra.payment.provider.wechat.wechat_signer import WeChatSigner

logger = logging.getLogger("web_infra.payment.wechat.client")

WECHAT_API_BASE = "https://api.mch.weixin.qq.com"


class WeChatPayClient:
    """微信支付 APIv3 请求客户端（自动签名/验签/错误映射）"""

    def __init__(self, config: WechatPayConfig, http_client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(config.read_timeout, connect=config.connect_timeout)
        )

    async def request(self, method: str, path: str, payload: dict | None = None, *, not_found_ok: bool = False) -> dict | None:
        """发起 APIv3 请求：自动签名、验签、错误映射；404 且 not_found_ok 返回 None"""
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if payload is not None else ""
        sign = WeChatSigner.request_signature(method, path, body, self._private_key_pem())
        headers = {
            "Authorization": WeChatSigner.authorization_header(
                self._config.mchid, self._config.mch_serial_no,
                sign["timestamp"], sign["nonce"], sign["signature"],
            ),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        url = f"{WECHAT_API_BASE}{path}"
        try:
            response = await self._http.request(method, url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            logger.error("微信支付请求异常 path=%s err=%s", path, exc)
            raise PaymentErrorCode.PAY_CHANNEL_ERROR.to_exception(message=f"微信支付请求失败：{exc}") from exc

        if response.status_code == 404 and not_found_ok:
            return None
        if response.status_code == 204:
            return {}
        if response.status_code >= 400:
            self._raise_wechat_error(path, response.status_code, response.text)
        self._verify_response(response.headers, response.text)
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise PaymentErrorCode.PAY_CHANNEL_ERROR.to_exception(message="微信支付响应格式错误") from exc

    def _private_key_pem(self) -> str:
        """商户 API 私钥（内容优先，其次文件路径）"""
        if self._config.private_key:
            return self._config.private_key
        with open(self._config.private_key_path, "r", encoding="utf-8") as f:
            return f.read()

    def _verify_response(self, headers: httpx.Headers, body: str) -> None:
        """应答验签（缺签名头时跳过，兼容测试/降级响应）"""
        timestamp = headers.get("Wechatpay-Timestamp", "")
        nonce = headers.get("Wechatpay-Nonce", "")
        signature = headers.get("Wechatpay-Signature", "")
        serial = headers.get("Wechatpay-Serial", "")
        if not all([timestamp, nonce, signature, serial]):
            return
        public_key = self._config.load_verify_key(serial)
        if public_key is None:
            raise PaymentErrorCode.PAY_CHANNEL_ERROR.to_exception(message=f"无匹配验签凭据 serial={serial}")
        if not WeChatSigner.verify_response(timestamp, nonce, body, signature, public_key):
            raise PaymentErrorCode.PAY_CHANNEL_ERROR.to_exception(message="微信支付应答验签失败")

    def _raise_wechat_error(self, path: str, status: int, body: str) -> None:
        """微信业务错误映射为 E3-PAY-000"""
        code = message = ""
        try:
            data = json.loads(body)
            code = data.get("code", "")
            message = data.get("message", "")
        except (ValueError, json.JSONDecodeError):
            pass
        logger.error("微信支付返回错误 path=%s status=%s code=%s message=%s", path, status, code, message)
        raise PaymentErrorCode.PAY_CHANNEL_ERROR.to_exception(message=f"微信支付错误[{code}]：{message}")
