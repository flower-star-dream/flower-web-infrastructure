"""
支付回调分发器单元测试

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 覆盖回调分发：注册处理器被调用、多处理器按序分发、无处理器静默兜底。
"""
from decimal import Decimal

import pytest

from web_infra.capabilities.payment.payment_callback import PaymentCallback
from web_infra.capabilities.payment.payment_callback_dispatcher import PaymentCallbackDispatcher
from web_infra.capabilities.payment.payment_callback_handler_interface import PaymentCallbackHandler


class _SpyHandler(PaymentCallbackHandler):
    """记录调用次数的测试处理器"""

    def __init__(self) -> None:
        self.calls: list[PaymentCallback] = []

    async def handle(self, callback: PaymentCallback) -> None:
        self.calls.append(callback)


@pytest.fixture
def callback() -> PaymentCallback:
    return PaymentCallback(event_type="TRANSACTION.SUCCESS", out_trade_no="T1", amount=Decimal("1.00"))


@pytest.mark.asyncio
async def test_dispatch_calls_all_handlers(callback):
    """dispatch：全部注册处理器被调用"""
    dispatcher = PaymentCallbackDispatcher()
    h1, h2 = _SpyHandler(), _SpyHandler()
    dispatcher.register(h1)
    dispatcher.register(h2)
    await dispatcher.dispatch(callback)
    assert len(h1.calls) == 1 and h1.calls[0] == callback
    assert len(h2.calls) == 1


@pytest.mark.asyncio
async def test_dispatch_unregister(callback):
    """unregister：注销后不再分发"""
    dispatcher = PaymentCallbackDispatcher()
    h1 = _SpyHandler()
    dispatcher.register(h1)
    dispatcher.unregister(h1)
    await dispatcher.dispatch(callback)
    assert h1.calls == []


@pytest.mark.asyncio
async def test_dispatch_without_handlers_no_error(callback):
    """dispatch：无处理器时不抛错（静默兜底）"""
    dispatcher = PaymentCallbackDispatcher()
    await dispatcher.dispatch(callback)  # 不应抛出
