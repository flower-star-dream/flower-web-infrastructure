"""
微信支付 APIv3 HTTP 客户端

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 微信支付 APIv3 请求客户端：自动附加请求签名头、应答验签、错误码映射、
              渠道调用失败兜底（网络/5xx/429 指数退避重试，默认开启可配置）。
              底层 httpx，可注入 transport 供测试（httpx.MockTransport）。
              平台证书自动下载：cert_auto_download 开启时，应答验签遇未知序列号自动
              调用 /v3/certificates 获取平台证书并缓存（防并发重复下载）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random

import httpx

from web_infra.error.web_infra_exception import WebInfraException
from web_infra.payment.payment_error_code import PaymentErrorCode
from web_infra.payment.payment_config import WechatPayConfig
from web_infra.payment.provider.wechat.wechat_certificate_store import WeChatCertificateStore
from web_infra.payment.provider.wechat.wechat_signer import WeChatSigner

logger = logging.getLogger("web_infra.payment.wechat.client")

WECHAT_API_BASE = "https://api.mch.weixin.qq.com"

# 重试抖动区间（乘数，防多实例同时重试造成重试风暴）
_RETRY_JITTER_MIN, _RETRY_JITTER_MAX = 0.5, 1.0


class WeChatPayClient:
    """微信支付 APIv3 请求客户端（自动签名/验签/错误映射/平台证书自动下载/失败重试兜底）"""

    def __init__(self, config: WechatPayConfig, http_client: httpx.AsyncClient | None = None,
                 cert_store: WeChatCertificateStore | None = None,
                 retries: int | None = None,
                 retry_delay_base: float | None = None,
                 retry_delay_max: float | None = None) -> None:
        """初始化客户端。

        :param config: 微信支付配置（含渠道失败重试默认参数 retries/retry_delay_base/retry_delay_max）
        :param http_client: 外部 httpx 客户端（测试注入 MockTransport 用）；缺省懒创建
        :param cert_store: 平台证书存储（缺省按配置创建）
        :param retries: 渠道调用失败重试次数（None 回落 config.retries，默认 2；0 关闭重试）
        :param retry_delay_base: 重试退避基数（秒，None 回落 config）
        :param retry_delay_max: 重试退避上限（秒，None 回落 config）
        """
        self._config = config
        self._http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(config.read_timeout, connect=config.connect_timeout)
        )
        self._cert_store = cert_store or WeChatCertificateStore(config)
        self._download_lock = asyncio.Lock()
        # 渠道调用失败兜底（支付接口 out_trade_no/out_refund_no 幂等，网络/5xx/429 可安全重试）
        self._retries = config.retries if retries is None else retries
        self._retry_delay_base = config.retry_delay_base if retry_delay_base is None else retry_delay_base
        self._retry_delay_max = config.retry_delay_max if retry_delay_max is None else retry_delay_max
        # 私钥文件缓存（P1 优化：按 mtime 失效，密钥轮换后自动重读）
        self._private_key_cache: tuple[str, float] = ("", 0.0)  # (pem 内容, 文件 mtime)

    async def request(self, method: str, path: str, payload: dict | None = None, *,
                      not_found_ok: bool = False, verify_response: bool = True,
                      retryable: bool = True) -> dict | None:
        """发起 APIv3 请求：自动签名、验签、错误映射；404 且 not_found_ok 返回 None。

        兜底策略：可重试故障（网络异常 / 微信 5xx / 429）按指数退避（含抖动）自动重试
        （默认 2 次，config.retries 可调，0 关闭）；4xx 业务错误与验签失败不重试。
        **重试边界（规范 §2.6/§7.2）**：仅**幂等接口**（查单/关单/退款，out_trade_no/out_refund_no
        天然幂等）允许自动重试；**下单（prepay）禁止盲目重试**（防重复下单/重复扣款），
        调用方传 `retryable=False`，失败由业务先查单确认再决策。重试耗尽抛 E3-PAY-000。

        :param verify_response: 是否校验应答签名（下载平台证书接口首次调用无证书可验，
                                传 False 跳过，参考官方 SDK 行为）
        :param retryable: 是否允许自动重试（非幂等接口如下单传 False，默认 True）
        """
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                return await self._request_once(
                    method, path, payload, not_found_ok=not_found_ok, verify_response=verify_response
                )
            except Exception as exc:  # noqa: BLE001 - 统一走可重试性判定
                last_error = exc
                if not retryable or not self._is_retriable_error(exc) or attempt >= self._retries:
                    raise
                delay = self._retry_delay(attempt)
                logger.warning(
                    "微信支付请求重试 path=%s attempt=%s delay=%ss err=%s",
                    path, attempt + 1, delay, exc,
                )
                await asyncio.sleep(delay)
        raise last_error  # 不可达（循环内已 raise/return）

    async def _request_once(self, method: str, path: str, payload: dict | None, *,
                            not_found_ok: bool, verify_response: bool) -> dict | None:
        """单次 APIv3 请求：签名头、HTTP 调用、错误分类映射（重试循环的原子单元）"""
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
            # 网络故障：可重试（data.retryable=True）
            raise PaymentErrorCode.PAY_CHANNEL_ERROR.to_exception(
                message=f"微信支付请求失败：{exc}", data={"http_status": 0, "retryable": True}
            ) from exc

        if response.status_code == 404 and not_found_ok:
            return None
        if response.status_code == 204:
            return {}
        if response.status_code >= 400:
            # 5xx / 429 可重试；其余 4xx 业务错误不可重试（参数/状态冲突，重试无意义）
            retryable = response.status_code == 429 or response.status_code >= 500
            self._raise_wechat_error(path, response.status_code, response.text, retryable=retryable)
        if verify_response:
            await self._verify_response(response.headers, response.text)
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise PaymentErrorCode.PAY_CHANNEL_ERROR.to_exception(message="微信支付响应格式错误") from exc

    async def download_certificates(self) -> None:
        """下载平台证书并缓存（GET /v3/certificates）；下载失败仅记日志不阻断调用方"""
        async with self._download_lock:
            try:
                data = await self.request("GET", "/v3/certificates", verify_response=False)
                items = (data or {}).get("data", [])
                if not items:
                    logger.warning("微信支付平台证书列表为空")
                    return
                self._cert_store.persist_certificates(items)
            except Exception as exc:  # 下载失败不阻断验签流程（验签继续失败由调用方回 401 重试）
                logger.error("微信支付平台证书下载失败：%s", exc)

    # ------------------------------------------------------------------
    # 内部：重试判定与退避
    # ------------------------------------------------------------------

    def _is_retriable_error(self, exc: Exception) -> bool:
        """是否可重试：网络故障（httpx.HTTPError）或携带 retryable 标记的渠道故障（5xx/429）。

        4xx 业务错误 / 验签失败 / 响应格式错误不带标记，不重试（由调用方按业务处理）。
        """
        if isinstance(exc, httpx.HTTPError):
            return True
        if isinstance(exc, WebInfraException) and exc.error_code.retryable:
            return bool((exc.data or {}).get("retryable"))
        return False

    def _retry_delay(self, attempt: int) -> float:
        """指数退避 + 抖动：min(base * 2^attempt * jitter, max)（防多实例重试风暴）"""
        jitter = random.uniform(_RETRY_JITTER_MIN, _RETRY_JITTER_MAX)
        return min(self._retry_delay_base * (2 ** attempt) * jitter, self._retry_delay_max)

    def _private_key_pem(self) -> str:
        """商户 API 私钥（内容优先，其次文件路径；文件按 mtime 缓存，P1 优化避免每次请求读盘）"""
        if self._config.private_key:
            return self._config.private_key
        mtime = os.path.getmtime(self._config.private_key_path)
        cached_pem, cached_mtime = self._private_key_cache
        if cached_pem and mtime == cached_mtime:
            return cached_pem
        with open(self._config.private_key_path, "r", encoding="utf-8") as f:
            pem = f.read()
        self._private_key_cache = (pem, mtime)
        return pem

    async def _verify_response(self, headers: httpx.Headers, body: str) -> None:
        """应答验签（缺签名头时跳过，兼容测试/降级响应）；未知序列号且开启自动下载时先下载再验"""
        timestamp = headers.get("Wechatpay-Timestamp", "")
        nonce = headers.get("Wechatpay-Nonce", "")
        signature = headers.get("Wechatpay-Signature", "")
        serial = headers.get("Wechatpay-Serial", "")
        if not all([timestamp, nonce, signature, serial]):
            return
        public_key = self._config.load_verify_key(serial)
        if public_key is None and self._config.verify_mode == "platform_cert" and self._config.cert_auto_download:
            logger.info("应答验签未知平台证书序列号 serial=%s，触发自动下载", serial)
            await self.download_certificates()
            public_key = self._config.load_verify_key(serial)
        if public_key is None:
            raise PaymentErrorCode.PAY_CHANNEL_ERROR.to_exception(message=f"无匹配验签凭据 serial={serial}")
        if not WeChatSigner.verify_response(timestamp, nonce, body, signature, public_key):
            raise PaymentErrorCode.PAY_CHANNEL_ERROR.to_exception(message="微信支付应答验签失败")

    def _raise_wechat_error(self, path: str, status: int, body: str, *, retryable: bool) -> None:
        """微信业务错误映射为 E3-PAY-000（data 携带 http_status 与可重试标记）。

        :param retryable: 是否可重试（5xx/429 为 True；4xx 参数/状态冲突为 False）
        """
        code = message = ""
        try:
            data = json.loads(body)
            code = data.get("code", "")
            message = data.get("message", "")
        except (ValueError, json.JSONDecodeError):
            pass
        logger.error("微信支付返回错误 path=%s status=%s code=%s message=%s", path, status, code, message)
        raise PaymentErrorCode.PAY_CHANNEL_ERROR.to_exception(
            message=f"微信支付错误[{code}]：{message}",
            data={"http_status": status, "retryable": retryable},
        )
