"""
支付冲正测试

@Author: 花海
@Date: 2026/08/17
@Description: 冲正流程（规范 §7.5）：新增反向冲正流水 + 标记原流水、幂等（重复执行返回首次）、
              禁止冲正冲正流水、下游补偿事件失败不阻塞冲正流水。
"""
from datetime import datetime
from decimal import Decimal

import pytest

from web_infra.payment import (
    InMemoryPaymentFlowStore,
    PaymentFlowRecord,
    PaymentFlowStatus,
    reversal_flow,
)
from web_infra.payment.payment_flow_status import PaymentFlowEvent


def _booked_flow(out_trade_no: str = "T1") -> PaymentFlowRecord:
    """构造已入账支付流水（冲正对象）"""
    return PaymentFlowRecord(
        out_trade_no=out_trade_no, event_type=PaymentFlowEvent.PAY,
        amount=Decimal("100.00"), status=PaymentFlowStatus.BOOKED,
        channel="memory", transaction_id="WX-1",
    )


@pytest.mark.asyncio
async def test_reversal_adds_reverse_flow_and_marks_original():
    """冲正：新增反向冲正流水 + 原流水标记已冲正（§7.5）"""
    flow_store = InMemoryPaymentFlowStore()
    original = await flow_store.append(_booked_flow())
    assert original.flow_id

    reversal = await reversal_flow(flow_store, original, channel="memory", reason="对账差异:LOCAL_ONLY")

    assert reversal.is_reversal is True
    assert reversal.original_flow_id == original.flow_id
    assert reversal.event_type == PaymentFlowEvent.REVERSAL
    assert reversal.status == PaymentFlowStatus.REVERSED
    assert reversal.amount == Decimal("100.00")  # 反向流水沿用原金额（反向语义由 is_reversal 表达）

    # 原流水标记已冲正（存储内聚行为，§7.5）
    stored = await flow_store.find_by_flow_id(original.flow_id)
    assert stored is not None
    assert stored.status == PaymentFlowStatus.REVERSED
    assert stored.reversed_at is not None


@pytest.mark.asyncio
async def test_reversal_idempotent():
    """冲正幂等：同一原流水重复冲正返回首次冲正流水（§7.5 唯一索引兜底）"""
    flow_store = InMemoryPaymentFlowStore()
    original = await flow_store.append(_booked_flow())

    first = await reversal_flow(flow_store, original)
    second = await reversal_flow(flow_store, original)

    assert second.flow_id == first.flow_id
    assert (await flow_store.find_reversal(original.flow_id)) is first


@pytest.mark.asyncio
async def test_reversal_rejects_reversing_reversal():
    """红线：禁止冲正冲正流水（§7.5）"""
    flow_store = InMemoryPaymentFlowStore()
    original = await flow_store.append(_booked_flow())
    reversal = await reversal_flow(flow_store, original)

    with pytest.raises(ValueError, match="禁止冲正冲正流水"):
        await reversal_flow(flow_store, reversal)


@pytest.mark.asyncio
async def test_reversal_event_callback_failure_not_blocking():
    """冲正事件：下游补偿失败不阻塞冲正流水本身（§7.5）"""
    flow_store = InMemoryPaymentFlowStore()
    original = await flow_store.append(_booked_flow())
    calls = []

    async def failing_callback(record):
        """下游补偿模拟失败"""
        calls.append(record.flow_id)
        raise RuntimeError("下游补偿失败")

    reversal = await reversal_flow(flow_store, original, event_callback=failing_callback)
    assert reversal.flow_id == calls[0]  # 事件已触发
    assert (await flow_store.find_by_flow_id(original.flow_id)).status == PaymentFlowStatus.REVERSED  # 冲正流水未被阻塞
