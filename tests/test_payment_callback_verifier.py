"""
回调验签 SPI 契约测试（内存默认实现）

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 以 InMemoryPaymentCallbackVerifier 验证 PaymentCallbackVerifier 契约。
"""
import pytest

from web_infra.capabilities.payment.in_memory_payment_callback_verifier import InMemoryPaymentCallbackVerifier
from web_infra.capabilities.payment.payment_callback import PaymentCallback


@pytest.mark.asyncio
async def test_parse_returns_configured_callback():
    """parse：返回构造回调"""
    cb = PaymentCallback(event_type="TRANSACTION.SUCCESS", out_trade_no="T1", amount=1)
    verifier = InMemoryPaymentCallbackVerifier(callback=cb)
    result = await verifier.parse({"wechatpay-serial": "S1"}, "{}")
    assert result == cb
    assert verifier.parsed == [({"wechatpay-serial": "S1"}, "{}")]


@pytest.mark.asyncio
async def test_parse_returns_none_by_default():
    """parse：未构造回调返回 None（验签失败语义）"""
    verifier = InMemoryPaymentCallbackVerifier()
    assert await verifier.parse({}, "") is None
