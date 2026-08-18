"""
支付订单超时自动关单任务单元测试

@Author: 花海
@Date: 2026/08/16
@Description: 覆盖规范 §5.5 超时自动关单：扫描超时未支付订单 → 骨架关单（查单确认）→ 本地 CLOSED；
              查单失败/渠道异常跳过（禁止在渠道状态不明时强行关单）。
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from web_infra.capabilities.payment import InMemoryPaymentOrderStore, PaymentLocalOrder
from web_infra.capabilities.payment.payment_close_task import close_expired_orders
from web_infra.capabilities.payment.payment_status import PaymentStatus
from tests.test_payment_channel_template import FakeChannel


def _expired_order(out_trade_no: str, amount: str = "10.00") -> PaymentLocalOrder:
    """构造超时未支付订单（失效时间已过）"""
    return PaymentLocalOrder(
        out_trade_no=out_trade_no,
        amount=Decimal(amount),
        status=PaymentStatus.NOTPAY,
        expire_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_close_expired_orders_closes_and_updates():
    """超时关单：超时未支付订单被关单（查单确认未支付 → 渠道关单 → 本地 CLOSED）"""
    order_store = InMemoryPaymentOrderStore()
    await order_store.save(_expired_order("T-EXP-1"))
    await order_store.save(_expired_order("T-EXP-2"))
    # 未超时订单不关
    await order_store.save(PaymentLocalOrder(
        out_trade_no="T-OK", amount=Decimal("10.00"),
        expire_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
    ))
    channel = FakeChannel(query_status=PaymentStatus.NOTPAY)

    closed = await close_expired_orders(
        order_store, channel, datetime.now(timezone.utc).replace(tzinfo=None), limit=100
    )
    assert closed == 2
    assert (await order_store.find_by_out_trade_no("T-EXP-1")).status == PaymentStatus.CLOSED
    assert (await order_store.find_by_out_trade_no("T-EXP-2")).status == PaymentStatus.CLOSED
    assert (await order_store.find_by_out_trade_no("T-OK")).status == PaymentStatus.NOTPAY


@pytest.mark.asyncio
async def test_close_expired_orders_skips_channel_paid():
    """超时关单：查单确认渠道已支付 → 跳过不关单（防已支付被关闭，§5.5），本地状态保持"""
    order_store = InMemoryPaymentOrderStore()
    await order_store.save(_expired_order("T-PAID"))
    channel = FakeChannel(query_status=PaymentStatus.SUCCESS)  # 渠道已支付

    closed = await close_expired_orders(order_store, channel, datetime.now(timezone.utc).replace(tzinfo=None))
    assert closed == 0
    assert (await order_store.find_by_out_trade_no("T-PAID")).status == PaymentStatus.NOTPAY


@pytest.mark.asyncio
async def test_close_expired_orders_skips_channel_error():
    """超时关单：查单/渠道异常 → 跳过该订单（记 WARN，下轮重试），不强行关单"""
    order_store = InMemoryPaymentOrderStore()
    await order_store.save(_expired_order("T-ERR"))

    class ErrorChannel(FakeChannel):
        """查单抛异常的渠道（模拟渠道不可用）"""

        async def _do_query_order(self, out_trade_no):
            raise RuntimeError("channel down")

    closed = await close_expired_orders(order_store, ErrorChannel(), datetime.now(timezone.utc).replace(tzinfo=None))
    assert closed == 0
    assert (await order_store.find_by_out_trade_no("T-ERR")).status == PaymentStatus.NOTPAY
