"""
支付回调验签解密接口

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 支付回调验签与解密 SPI：解析渠道回调 headers+body 为统一回调结构。
              验签失败/解密失败返回 None（调用方返回 401，渠道将自动重试）。
"""
from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from web_infra.capabilities.payment.payment_callback import PaymentCallback


@runtime_checkable
class PaymentCallbackVerifier(Protocol):
    """支付回调验签与解密 SPI"""

    async def parse(self, headers: Mapping[str, str], body: str) -> PaymentCallback | None:
        """解析渠道回调请求头与报文为统一回调；失败返回 None"""
        ...
