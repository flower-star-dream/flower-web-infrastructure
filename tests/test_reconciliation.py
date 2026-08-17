"""
对账机制测试

@Author: 花海
@Date: 2026/08/17
@Description: 对账（规范 §6）：对齐一致、五类差异分类（§6.3）、自动处理（§6.4：查单确认后
              补记/冲正，金额不一致强制人工 P0 告警）、任务防重（§6.5）、审计落库（§6.6 只增不改）、
              账单文件管理（§6.7 校验/存储/归档/重下）。
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from web_infra.payment import (
    InMemoryPaymentFlowStore,
    InMemoryReconciliationAuditStore,
    PaymentFlowRecord,
    PaymentFlowStatus,
    PaymentStatus,
)
from web_infra.payment.payment_flow_status import PaymentFlowEvent
from web_infra.payment.reconciliation import (
    BillFileManager,
    BillRecord,
    DifferenceType,
    ReconciliationService,
    run_reconciliation,
)


def _flow(out_trade_no: str, event: PaymentFlowEvent = PaymentFlowEvent.PAY,
          amount: str = "10.00", status: PaymentFlowStatus = PaymentFlowStatus.BOOKED) -> PaymentFlowRecord:
    """构造本地流水"""
    return PaymentFlowRecord(out_trade_no=out_trade_no, event_type=event, amount=Decimal(amount), status=status)


def _bill(out_trade_no: str, event: PaymentFlowEvent = PaymentFlowEvent.PAY,
          amount: str = "10.00", status: str = "SUCCESS") -> BillRecord:
    """构造渠道账单明细"""
    return BillRecord(out_trade_no=out_trade_no, event_type=event, amount=Decimal(amount), status=status)


# ---------------------------------------------------------------------------
# 对齐与差异分类（§6.2/§6.3）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_matched():
    """对账：账单与本地流水全部对齐 → 无差异"""
    service = ReconciliationService(InMemoryPaymentFlowStore(), InMemoryReconciliationAuditStore())
    flows = [_flow("T1"), _flow("T2", amount="20.00")]
    bills = [_bill("T1"), _bill("T2", amount="20.00")]
    result = await service.reconcile(bills, flows, channel="wechat", biz_date="2026-08-16")
    assert result.matched_count == 2
    assert result.difference_count == 0


@pytest.mark.asyncio
async def test_reconcile_channel_only_difference():
    """差异：渠道有本地无（长款，回调丢失）→ 查单确认后自动补记（§6.4/§6.6 兜底）"""
    flow_store = InMemoryPaymentFlowStore()
    service = ReconciliationService(
        flow_store, InMemoryReconciliationAuditStore(),
        query_order=_asyncio_order(PaymentStatus.SUCCESS),
    )
    bills = [_bill("LOST-1")]
    result = await service.reconcile(bills, [], channel="wechat", biz_date="2026-08-16")
    assert result.auto_booked == 1
    assert result.differences[0].diff_type == DifferenceType.CHANNEL_ONLY
    # 补记流水已落库（回调缺失兜底，§6.6）
    booked = await flow_store.find_by_order_and_event("LOST-1", PaymentFlowEvent.PAY)
    assert booked is not None
    assert booked.status == PaymentFlowStatus.BOOKED


@pytest.mark.asyncio
async def test_reconcile_local_only_auto_reversed():
    """差异：本地有渠道无（短款，本地误记）→ 查单确认未支付 → 自动冲正（§6.4/§7.5）"""
    flow_store = InMemoryPaymentFlowStore()
    original = await flow_store.append(_flow("GHOST-1"))
    service = ReconciliationService(
        flow_store, InMemoryReconciliationAuditStore(),
        query_order=_asyncio_order(PaymentStatus.NOTPAY),
    )
    flows = [_flow("GHOST-1")]
    result = await service.reconcile([], flows, channel="wechat", biz_date="2026-08-16")
    assert result.auto_reversed == 1
    assert result.differences[0].diff_type == DifferenceType.LOCAL_ONLY
    # 原流水已冲正 + 冲正流水存在（§7.5）
    reversal = await flow_store.find_reversal(original.flow_id)
    assert reversal is not None and reversal.is_reversal is True
    assert (await flow_store.find_by_flow_id(original.flow_id)).status == PaymentFlowStatus.REVERSED


@pytest.mark.asyncio
async def test_reconcile_amount_mismatch_manual():
    """差异：金额不一致（极高）→ 挂账 P0 告警人工，禁止自动动账（§6.3/§6.4）"""
    service = ReconciliationService(InMemoryPaymentFlowStore(), InMemoryReconciliationAuditStore())
    flows = [_flow("AMT-1", amount="10.00")]
    bills = [_bill("AMT-1", amount="99.00")]
    result = await service.reconcile(bills, flows, channel="wechat", biz_date="2026-08-16")
    assert result.manual_count == 1
    diff = result.differences[0]
    assert diff.diff_type == DifferenceType.AMOUNT_MISMATCH
    assert diff.severity.value == "CRITICAL"
    assert diff.handled is False  # 未自动处理


@pytest.mark.asyncio
async def test_concurrent_reconcile_no_channel_leak():
    """并发安全：同一 service 实例并发 reconcile（不同渠道/账期）不串号（H1 修复）"""
    import asyncio

    flow_store = InMemoryPaymentFlowStore()
    service = ReconciliationService(
        flow_store, InMemoryReconciliationAuditStore(),
        query_order=_asyncio_order(PaymentStatus.SUCCESS),
    )
    # 两轮并发对账（不同渠道/账期，各有 CHANNEL_ONLY 差异）→ 补记流水须带各自渠道/账期
    results = await asyncio.gather(
        service.reconcile([_bill("A-1")], [], channel="wechat", biz_date="2026-08-16"),
        service.reconcile([_bill("B-1")], [], channel="alipay", biz_date="2026-08-17"),
    )
    booked_a = await flow_store.find_by_order_and_event("A-1", PaymentFlowEvent.PAY)
    booked_b = await flow_store.find_by_order_and_event("B-1", PaymentFlowEvent.PAY)
    assert booked_a is not None and booked_a.channel == "wechat"
    assert booked_a.raw.get("biz_date") == "2026-08-16"
    assert booked_b is not None and booked_b.channel == "alipay"
    assert booked_b.raw.get("biz_date") == "2026-08-17"
    assert results[0].auto_booked == 1 and results[1].auto_booked == 1


@pytest.mark.asyncio
async def test_reconcile_audit_and_duplicate_skip():
    """任务防重：同渠道 + 账期已对账 → 第二轮跳过（§6.5/§6.6）"""
    service = ReconciliationService(InMemoryPaymentFlowStore(), InMemoryReconciliationAuditStore())
    result = await run_reconciliation(
        service, channel="wechat", biz_date="2026-08-16",
        bill_provider=lambda: _asyncio_value([_bill("T1")]),
        flow_provider=lambda: _asyncio_value([_flow("T1")]),
    )
    assert result is not None and result.matched_count == 1
    # 审计已落库（§6.6 只增不改）
    assert await service.is_reconciled("wechat", "2026-08-16") is True
    # 防重：同账期再跑 → None
    second = await run_reconciliation(
        service, channel="wechat", biz_date="2026-08-16",
        bill_provider=lambda: _asyncio_value([_bill("T1")]),
        flow_provider=lambda: _asyncio_value([_flow("T1")]),
    )
    assert second is None


# ---------------------------------------------------------------------------
# 账单文件管理（§6.7）
# ---------------------------------------------------------------------------


def test_bill_file_save_and_load(tmp_path: Path):
    """账单文件：校验通过 → 按账期落盘 + 可读取（§6.7）"""
    manager = BillFileManager(tmp_path, expected_header="#bill", expected_length=4)
    biz_date = date(2026, 8, 16)
    path = manager.save("wechat", biz_date, b"#bill,t1,10.00\n")
    assert path.exists()
    assert manager.load("wechat", biz_date) == b"#bill,t1,10.00\n"
    assert (tmp_path / "wechat" / "2026-08-16").is_dir()  # 按账期组织


def test_bill_file_integrity_rejected(tmp_path: Path):
    """账单文件：文件头不符/校验和不匹配 → 完整性校验失败丢弃（§6.7）"""
    manager = BillFileManager(tmp_path, expected_header="#bill")
    with pytest.raises(ValueError, match="文件头不符"):
        manager.save("wechat", date(2026, 8, 16), b"garbage,data\n")
    with pytest.raises(ValueError, match="校验和不匹配"):
        manager.save("wechat", date(2026, 8, 15), b"#bill,t1\n", checksum="deadbeef")


def test_bill_file_corrupted_reload_returns_none(tmp_path: Path):
    """账单文件：已存文件损坏（校验失败）→ 读取返回 None 并删除，触发重下（§6.7）"""
    manager = BillFileManager(tmp_path, expected_header="#bill")
    biz_date = date(2026, 8, 16)
    manager.save("wechat", biz_date, b"#bill,ok\n")
    # 模拟文件被篡改
    (tmp_path / "wechat" / "2026-08-16" / "wechat_2026-08-16.bill").write_bytes(b"tampered")
    assert manager.load("wechat", biz_date) is None


def test_bill_file_cleanup_expired(tmp_path: Path):
    """账单文件：保留期外清理（§6.7，与流水追溯窗口一致 ≥ 90 天）"""
    manager = BillFileManager(tmp_path, retain_days=90)
    old = date(2020, 1, 1)
    recent = date.today()
    manager.save("wechat", old, b"#bill,old\n")
    manager.save("wechat", recent, b"#bill,new\n")
    removed = manager.cleanup_expired()
    assert removed == 1
    assert manager.load("wechat", old) is None
    assert manager.load("wechat", recent) is not None


def _channel_order(out_trade_no: str, status: PaymentStatus):
    """查单回调模拟（渠道权威状态）"""
    from web_infra.payment import PaymentOrder

    return PaymentOrder(out_trade_no=out_trade_no, status=status, total_amount=Decimal("10.00"), payer_total=Decimal("10.00"))


def _asyncio_order(status: PaymentStatus):
    """构造 async 查单回调（固定渠道状态，§6.4 未确认不处理资金）"""

    async def _query(out_trade_no: str):
        return _channel_order(out_trade_no, status)

    return _query


def _asyncio_value(value):
    """同步值包装为可 await 结果（provider 回调为 async，测试简化）"""
    import asyncio

    async def _wrap():
        return value

    return _wrap()
