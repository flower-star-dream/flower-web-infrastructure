"""
渠道骨架类单元测试

@Author: 花海
@Date: 2026/08/16
@Description: 覆盖渠道骨架层（PaymentChannelTemplate，规范 §3.1）的 final 流程：
              下单幂等检查、退款能力位（E4-PAY-008）、关单本地幂等 + 查单确认（§5.5）、
              回调通用层校验（金额 E4-PAY-002 / attach / 状态机 §4.3）、流水落库（§5.2）、
              支付状态机（§4.5 合法流转 / 幂等重复 / 非法冲突）。
"""
from decimal import Decimal
from typing import Any, Mapping

import pytest

from web_infra.capabilities.payment import (
    InMemoryPaymentFlowStore,
    InMemoryPaymentOrderStore,
    PaymentCallback,
    PaymentChannelTemplate,
    PaymentErrorCode,
    PaymentLocalOrder,
    PaymentPrepayRequest,
    PaymentPrepayResponse,
    PaymentScene,
    PaymentStateMachine,
)
from web_infra.capabilities.payment.payment_flow_status import PaymentFlowEvent, PaymentFlowStatus
from web_infra.capabilities.payment.payment_status import PaymentEvent, PaymentStatus


class FakeChannel(PaymentChannelTemplate):
    """假渠道：只填充渠道特有 _do_*，验证骨架 final 流程"""

    capabilities = frozenset({"query_order", "close_order", "parse_callback", "refund", "query_refund"})

    def __init__(self, *, flow_store=None, order_store=None, query_status: PaymentStatus = PaymentStatus.NOTPAY) -> None:
        super().__init__(flow_store=flow_store, order_store=order_store)
        self.query_status = query_status
        self.prepay_called = False
        self.close_called = False
        self.refund_called = False
        self.next_callback: PaymentCallback | None = None

    async def _do_prepay(self, request: PaymentPrepayRequest) -> PaymentPrepayResponse:
        self.prepay_called = True
        return PaymentPrepayResponse(scene=request.scene, prepay_id="prepay-1")

    async def _do_query_order(self, out_trade_no: str) -> Any:
        from web_infra.capabilities.payment import PaymentOrder

        return PaymentOrder(
            out_trade_no=out_trade_no, status=self.query_status,
            total_amount=Decimal("10.00"), payer_total=Decimal("10.00"),
        )

    async def _do_close_order(self, out_trade_no: str) -> None:
        self.close_called = True

    async def _parse_callback(self, headers: Mapping[str, str], body: str) -> PaymentCallback | None:
        return self.next_callback

    async def _do_refund(self, request: Any) -> Any:
        from web_infra.capabilities.payment import PaymentRefundResponse

        self.refund_called = True
        return PaymentRefundResponse(out_refund_no=request.out_refund_no, refund_id="REF-1", refund_amount=request.refund_amount)


# ---------------------------------------------------------------------------
# 下单幂等（§4.2）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepay_checks_local_order_state():
    """下单幂等：本地订单已 SUCCESS/进行中 → 拒绝下单（E4-PAY-003，§4.2）"""
    order_store = InMemoryPaymentOrderStore()
    await order_store.save(PaymentLocalOrder(out_trade_no="T1", amount=Decimal("10.00"), status=PaymentStatus.SUCCESS))
    channel = FakeChannel(order_store=order_store)
    with pytest.raises(Exception) as exc_info:
        await channel.prepay(PaymentPrepayRequest(scene=PaymentScene.NATIVE, out_trade_no="T1", description="x", total_amount=Decimal("10.00")))
    assert exc_info.value.code == PaymentErrorCode.PAY_ORDER_STATE_CONFLICT.code
    assert channel.prepay_called is False  # 未透传渠道


# ---------------------------------------------------------------------------
# 退款能力位（§3.4：E4-PAY-008）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refund_unsupported_capability():
    """退款能力位：未声明 refund 的渠道调用退款 → E4-PAY-008（禁止透传渠道）"""

    class NoRefundChannel(PaymentChannelTemplate):
        capabilities = frozenset({"query_order", "close_order", "parse_callback"})

        async def _do_prepay(self, request):  # pragma: no cover
            raise NotImplementedError

        async def _do_query_order(self, out_trade_no):  # pragma: no cover
            raise NotImplementedError

        async def _do_close_order(self, out_trade_no):  # pragma: no cover
            raise NotImplementedError

        async def _parse_callback(self, headers, body):  # pragma: no cover
            raise NotImplementedError

    from web_infra.capabilities.payment import PaymentRefundRequest

    channel = NoRefundChannel()
    with pytest.raises(Exception) as exc_info:
        await channel.refund(PaymentRefundRequest(out_trade_no="T1", out_refund_no="R1", refund_amount=Decimal("1.00"), total_amount=Decimal("10.00")))
    assert exc_info.value.code == PaymentErrorCode.PAY_CAPABILITY_UNSUPPORTED.code


# ---------------------------------------------------------------------------
# 关单（§5.5）：本地幂等 + 查单确认
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_order_local_idempotent_closed():
    """关单本地幂等：本地已 CLOSED → 直接返回，不调渠道（§5.5）"""
    order_store = InMemoryPaymentOrderStore()
    await order_store.save(PaymentLocalOrder(out_trade_no="T1", amount=Decimal("10.00"), status=PaymentStatus.CLOSED))
    channel = FakeChannel(order_store=order_store)
    await channel.close_order("T1")
    assert channel.close_called is False  # 未调渠道关单


@pytest.mark.asyncio
async def test_close_order_local_success_conflict():
    """关单：本地已 SUCCESS → 抛 E4-PAY-003 禁止关单（§5.5）"""
    order_store = InMemoryPaymentOrderStore()
    await order_store.save(PaymentLocalOrder(out_trade_no="T1", amount=Decimal("10.00"), status=PaymentStatus.SUCCESS))
    channel = FakeChannel(order_store=order_store)
    with pytest.raises(Exception) as exc_info:
        await channel.close_order("T1")
    assert exc_info.value.code == PaymentErrorCode.PAY_ORDER_STATE_CONFLICT.code


@pytest.mark.asyncio
async def test_close_order_channel_paid_conflict():
    """关单：查单确认渠道已支付 → 抛 E4-PAY-003，禁止关单（防已支付被关闭）"""
    channel = FakeChannel(query_status=PaymentStatus.SUCCESS)
    with pytest.raises(Exception) as exc_info:
        await channel.close_order("T1")
    assert exc_info.value.code == PaymentErrorCode.PAY_ORDER_STATE_CONFLICT.code
    assert channel.close_called is False


@pytest.mark.asyncio
async def test_close_order_writes_close_flow():
    """关单：查单确认未支付 → 关单成功并落 CLOSE 流水（§5.2/§5.5）"""
    flow_store = InMemoryPaymentFlowStore()
    channel = FakeChannel(flow_store=flow_store, query_status=PaymentStatus.NOTPAY)
    await channel.close_order("T1")
    assert channel.close_called is True
    flow = await flow_store.find_by_order_and_event("T1", PaymentFlowEvent.CLOSE)
    assert flow is not None
    assert flow.status == PaymentFlowStatus.CLOSED


# ---------------------------------------------------------------------------
# 回调入账（§4.3）：金额/attach/状态机 + 流水落库
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_amount_mismatch_rejected():
    """回调金额与本地订单不符 → E4-PAY-002 拒绝入账（§4.3）"""
    order_store = InMemoryPaymentOrderStore()
    await order_store.save(PaymentLocalOrder(out_trade_no="T1", amount=Decimal("10.00")))
    channel = FakeChannel(order_store=order_store)
    channel.next_callback = PaymentCallback(
        event_type="TRANSACTION.SUCCESS", out_trade_no="T1", amount=Decimal("99.00"),
    )
    with pytest.raises(Exception) as exc_info:
        await channel.handle_callback({}, "")
    assert exc_info.value.code == PaymentErrorCode.PAY_AMOUNT_MISMATCH.code


@pytest.mark.asyncio
async def test_callback_attach_mismatch_rejected():
    """回调 attach 与本地订单不符 → 拒绝入账（§4.3）"""
    order_store = InMemoryPaymentOrderStore()
    await order_store.save(PaymentLocalOrder(out_trade_no="T1", amount=Decimal("10.00"), attach="order-abc"))
    channel = FakeChannel(order_store=order_store)
    channel.next_callback = PaymentCallback(
        event_type="TRANSACTION.SUCCESS", out_trade_no="T1", amount=Decimal("10.00"), attach="order-xyz",
    )
    with pytest.raises(Exception) as exc_info:
        await channel.handle_callback({}, "")
    assert exc_info.value.code == PaymentErrorCode.PAY_AMOUNT_MISMATCH.code


@pytest.mark.asyncio
async def test_callback_success_transitions_and_books():
    """回调入账：NOTPAY + PAY_SUCCESS → 订单 SUCCESS + PAY 流水已入账（§4.5/§5.2）"""
    order_store = InMemoryPaymentOrderStore()
    flow_store = InMemoryPaymentFlowStore()
    await order_store.save(PaymentLocalOrder(out_trade_no="T1", amount=Decimal("10.00")))
    channel = FakeChannel(order_store=order_store, flow_store=flow_store)
    channel.next_callback = PaymentCallback(
        event_type="TRANSACTION.SUCCESS", out_trade_no="T1", amount=Decimal("10.00"),
        transaction_id="WX-1", raw={"mchid": "1"},
    )
    await channel.handle_callback({}, "")
    local = await order_store.find_by_out_trade_no("T1")
    assert local.status == PaymentStatus.SUCCESS
    flow = await flow_store.find_by_order_and_event("T1", PaymentFlowEvent.PAY)
    assert flow is not None
    assert flow.status == PaymentFlowStatus.BOOKED
    assert flow.transaction_id == "WX-1"


@pytest.mark.asyncio
async def test_callback_repeat_idempotent():
    """重复回调幂等：SUCCESS 订单收到重复支付回调 → 幂等返回，不抛冲突（§4.3）"""
    order_store = InMemoryPaymentOrderStore()
    flow_store = InMemoryPaymentFlowStore()
    await order_store.save(PaymentLocalOrder(out_trade_no="T1", amount=Decimal("10.00"), status=PaymentStatus.SUCCESS))
    channel = FakeChannel(order_store=order_store, flow_store=flow_store)
    channel.next_callback = PaymentCallback(event_type="TRANSACTION.SUCCESS", out_trade_no="T1", amount=Decimal("10.00"))
    await channel.handle_callback({}, "")  # 不抛异常：幂等重复成功
    # 状态机幂等：SUCCESS + PAY_SUCCESS 返回 SUCCESS，不抛冲突
    assert PaymentStateMachine.is_idempotent_repeat(PaymentStatus.SUCCESS, PaymentEvent.PAY_SUCCESS) is True
    assert PaymentStateMachine.target(PaymentStatus.SUCCESS, PaymentEvent.PAY_SUCCESS) == PaymentStatus.SUCCESS


@pytest.mark.asyncio
async def test_callback_closed_order_conflict():
    """CLOSED 订单收到支付回调 → 状态机拒绝（E4-PAY-003，§4.5 终态不可逆）"""
    order_store = InMemoryPaymentOrderStore()
    await order_store.save(PaymentLocalOrder(out_trade_no="T1", amount=Decimal("10.00"), status=PaymentStatus.CLOSED))
    channel = FakeChannel(order_store=order_store)
    channel.next_callback = PaymentCallback(event_type="TRANSACTION.SUCCESS", out_trade_no="T1", amount=Decimal("10.00"))
    with pytest.raises(Exception) as exc_info:
        await channel.handle_callback({}, "")
    assert exc_info.value.code == PaymentErrorCode.PAY_ORDER_STATE_CONFLICT.code


# ---------------------------------------------------------------------------
# 支付状态机（§4.5）
# ---------------------------------------------------------------------------


def test_state_machine_legal_transitions():
    """状态机合法流转（§4.5 权威状态定义）"""
    assert PaymentStateMachine.target(PaymentStatus.NOTPAY, PaymentEvent.PAY_SUCCESS) == PaymentStatus.SUCCESS
    assert PaymentStateMachine.target(PaymentStatus.NOTPAY, PaymentEvent.PAY_FAILED) == PaymentStatus.PAYERROR
    assert PaymentStateMachine.target(PaymentStatus.NOTPAY, PaymentEvent.CLOSE) == PaymentStatus.CLOSED
    assert PaymentStateMachine.target(PaymentStatus.USERPAYING, PaymentEvent.CONFIRM_EXCEED) == PaymentStatus.EXCEPTION
    assert PaymentStateMachine.target(PaymentStatus.EXCEPTION, PaymentEvent.RECONCILE_SUCCESS) == PaymentStatus.SUCCESS
    assert PaymentStateMachine.target(PaymentStatus.SUCCESS, PaymentEvent.REFUND_SUCCESS) == PaymentStatus.REFUND


def test_state_machine_illegal_transition_rejected():
    """状态机非法流转 → E4-PAY-003"""
    with pytest.raises(Exception) as exc_info:
        PaymentStateMachine.target(PaymentStatus.CLOSED, PaymentEvent.PAY_SUCCESS)
    assert exc_info.value.code == PaymentErrorCode.PAY_ORDER_STATE_CONFLICT.code


def test_state_machine_terminal_and_idempotent():
    """状态机终态判定与幂等重复（§4.5）"""
    assert PaymentStateMachine.is_terminal(PaymentStatus.SUCCESS) is True
    assert PaymentStateMachine.is_terminal(PaymentStatus.EXCEPTION) is False  # EXCEPTION 非终态
    assert PaymentStateMachine.is_idempotent_repeat(PaymentStatus.SUCCESS, PaymentEvent.PAY_SUCCESS) is True


# ---------------------------------------------------------------------------
# 退款超额（§5.3）+ 金额换算边界（§8.1/§10.3）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refund_exceeds_paid_amount_rejected():
    """退款超额：已退 + 本次 > 实付金额 → 拒绝（§5.3 部分退款累计约束）"""
    from decimal import Decimal

    from web_infra.capabilities.payment import PaymentFlowRecord, PaymentRefundRequest
    from web_infra.capabilities.payment.payment_flow_status import PaymentFlowEvent

    order_store = InMemoryPaymentOrderStore()
    flow_store = InMemoryPaymentFlowStore()
    await order_store.save(PaymentLocalOrder(out_trade_no="T1", amount=Decimal("10.00"), status=PaymentStatus.SUCCESS))
    # 已退 6 元
    await flow_store.append(PaymentFlowRecord(out_trade_no="T1", event_type=PaymentFlowEvent.REFUND, amount=Decimal("6.00")))
    channel = FakeChannel(order_store=order_store, flow_store=flow_store)
    with pytest.raises(Exception) as exc_info:
        await channel.refund(PaymentRefundRequest(out_trade_no="T1", out_refund_no="R1", refund_amount=Decimal("5.00"), total_amount=Decimal("10.00")))
    assert exc_info.value.code == "E4-COMMON-001"  # COMMON_CONFLICT：退款超实付
    assert channel.refund_called is False  # 未透传渠道


def test_amount_fen_yuan_conversion_boundaries():
    """金额换算边界（§8.1/§10.3）：元→分、分→元边界值（0.01 / 99999999.99）"""
    from web_infra.capabilities.payment.provider.wechat.wechat_pay_provider import WeChatPayProvider

    assert WeChatPayProvider._to_fen(Decimal("0.01")) == 1
    assert WeChatPayProvider._to_yuan(1) == Decimal("0.01")
    assert WeChatPayProvider._to_fen(Decimal("99999999.99")) == 9999999999
    assert WeChatPayProvider._to_yuan(9999999999) == Decimal("99999999.99")
    # 两位小数内换算往返一致
    assert WeChatPayProvider._to_yuan(WeChatPayProvider._to_fen(Decimal("1234.56"))) == Decimal("1234.56")
