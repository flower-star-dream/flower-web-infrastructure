"""
风控限额与支付审计测试

@Author: 花海
@Date: 2026/08/17
@Description: 风控限额（规范 §9）：单笔限额 E4-PAY-005、日/月累计限额（Decimal 精确 + 原子）、
              频次控制 E4-PAY-006、可疑拆分拦截 E4-PAY-007、未配置不限制。
              支付审计（§8.3）：只增不改、同 audit_id 幂等、失败同样留痕。
"""
from decimal import Decimal

import pytest

from web_infra.capabilities.payment import (
    InMemoryLimitCounterStore,
    InMemoryPaymentAuditStore,
    PaymentAuditRecord,
    PaymentErrorCode,
    PaymentLimitConfig,
    PaymentRiskGuard,
)
from web_infra.capabilities.payment.risk.payment_limit_config import LimitRule


@pytest.fixture
def guard() -> PaymentRiskGuard:
    """风控守卫（内存计数存储）"""
    return PaymentRiskGuard(InMemoryLimitCounterStore())


@pytest.mark.asyncio
async def test_per_transaction_limit_rejected(guard):
    """单笔限额（§9.1）：超限抛 E4-PAY-005"""
    rule = LimitRule(per_transaction=Decimal("1000"))
    with pytest.raises(Exception) as exc_info:
        await guard.check_prepay(1, "wechat", Decimal("1000.01"), rule)
    assert exc_info.value.code == PaymentErrorCode.PAY_LIMIT_EXCEEDED.code


@pytest.mark.asyncio
async def test_daily_limit_rejected(guard):
    """日累计限额（§9.1）：累计超限抛 E4-PAY-005（Decimal 精确累加）"""
    rule = LimitRule(daily_limit=Decimal("1000"))
    await guard.check_prepay(1, "wechat", Decimal("600"), rule)
    await guard.check_prepay(1, "wechat", Decimal("400"), rule)
    with pytest.raises(Exception) as exc_info:
        await guard.check_prepay(1, "wechat", Decimal("0.01"), rule)
    assert exc_info.value.code == PaymentErrorCode.PAY_LIMIT_EXCEEDED.code
    # 不同用户互不影响
    await guard.check_prepay(2, "wechat", Decimal("1000"), rule)


@pytest.mark.asyncio
async def test_frequency_limit_rejected(guard):
    """频次控制（§9.2）：窗口内超限抛 E4-PAY-006"""
    rule = LimitRule(frequency_window_seconds=3600, max_attempts=3)
    for _ in range(3):
        await guard.check_prepay(1, "wechat", Decimal("1"), rule)
    with pytest.raises(Exception) as exc_info:
        await guard.check_prepay(1, "wechat", Decimal("1"), rule)
    assert exc_info.value.code == PaymentErrorCode.PAY_FREQUENCY_LIMITED.code


@pytest.mark.asyncio
async def test_suspicious_split_blocked(guard):
    """可疑拆分（§9.3）：窗口内多笔接近单笔限额 → E4-PAY-007 风控拦截"""
    rule = LimitRule(per_transaction=Decimal("1000"), suspicious_split_count=3, suspicious_split_ratio=Decimal("0.9"))
    for _ in range(2):
        await guard.check_prepay(1, "wechat", Decimal("950"), rule)  # 950 ≥ 900（90% 单笔限额）
    with pytest.raises(Exception) as exc_info:
        await guard.check_prepay(1, "wechat", Decimal("950"), rule)
    assert exc_info.value.code == PaymentErrorCode.PAY_RISK_BLOCKED.code


@pytest.mark.asyncio
async def test_no_rule_no_limit(guard):
    """未配置规则：不限制（配置化，§9.1）"""
    await guard.check_prepay(1, "wechat", Decimal("999999"), LimitRule())


# ---------------------------------------------------------------------------
# 支付审计（§8.3）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_append_only_and_idempotent():
    """审计：只增不改 + 同 audit_id 幂等（§8.3）"""
    store = InMemoryPaymentAuditStore()
    record = PaymentAuditRecord(
        action="callback", out_trade_no="T1", amount="10.00", channel="wechat",
        result="success", trace_id="trace-1", raw={"event": "TRANSACTION.SUCCESS"},
    )
    first = await store.append(record)
    second = await store.append(record)
    assert second.audit_id == first.audit_id  # 幂等
    records = await store.list_all()
    assert len(records) == 1  # 只增不改：不重复写入
    assert records[0].trace_id == "trace-1"
    assert records[0].raw == {"event": "TRANSACTION.SUCCESS"}  # 原始报文仅落审计（§8.6）


@pytest.mark.asyncio
async def test_audit_records_failure_too():
    """审计：失败/拒绝同样留痕（§8.3 失败与异常同样留痕）"""
    store = InMemoryPaymentAuditStore()
    await store.append(PaymentAuditRecord(action="prepay", out_trade_no="T2", amount="50.00", channel="wechat", result="failed", detail="渠道 5xx"))
    await store.append(PaymentAuditRecord(action="refund", out_trade_no="T2", amount="20.00", channel="wechat", result="rejected", detail="退款超额"))
    records = await store.list_all()
    assert len(records) == 2
    assert {r.result for r in records} == {"failed", "rejected"}


def test_permission_points_defined():
    """权限点（§8.4）：高风险操作（退款/冲正/对账）独立权限点，AUTH_PERM_ 前缀"""
    from web_infra.capabilities.payment import PaymentPermission

    assert PaymentPermission.AUTH_PERM_PAY_REFUND.startswith("AUTH_PERM_")
    assert PaymentPermission.AUTH_PERM_PAY_REVERSAL.startswith("AUTH_PERM_")
    assert PaymentPermission.AUTH_PERM_PAY_RECONCILE.startswith("AUTH_PERM_")
    assert PaymentPermission.AUTH_PERM_PAY_REFUND != PaymentPermission.AUTH_PERM_PAY_REVERSAL  # 高风险操作隔离（§8.4）
