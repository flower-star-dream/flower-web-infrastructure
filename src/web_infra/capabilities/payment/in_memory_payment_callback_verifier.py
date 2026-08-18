"""
内存回调验签器（测试默认实现）

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 内存回调验签器（PaymentCallbackVerifier SPI 默认实现）：构造模式下直接返回
              注入的回调（未注入返回 None，对应验签失败语义），供单机/测试场景使用。
"""
from __future__ import annotations

from typing import Mapping

from web_infra.capabilities.payment.payment_callback import PaymentCallback
from web_infra.capabilities.payment.payment_callback_verifier_interface import PaymentCallbackVerifier


class InMemoryPaymentCallbackVerifier(PaymentCallbackVerifier):
    """内存回调验签器（PaymentCallbackVerifier SPI 默认实现）"""

    def __init__(self, callback: PaymentCallback | None = None) -> None:
        self._callback = callback
        self.parsed: list[tuple[Mapping[str, str], str]] = []

    async def parse(self, headers: Mapping[str, str], body: str) -> PaymentCallback | None:
        self.parsed.append((headers, body))
        return self._callback
