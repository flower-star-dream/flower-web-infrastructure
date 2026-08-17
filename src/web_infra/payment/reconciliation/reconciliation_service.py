"""
对账服务（ReconciliationService）

@Author: 花海
@Date: 2026/08/17
@Description: 对账编排（规范 §6.2 流程）：渠道账单（统一明细）vs 本地支付流水按
              「订单号 + 事件类型 + 金额」对齐 → 差异分类（§6.3 五类）→ 自动处理（§6.4：
              CHANNEL_ONLY 查单确认后补记；LOCAL_ONLY 查单确认未支付后冲正；金额/状态不一致
              挂账 P0 告警人工）→ 审计落库（§6.6 只增不改）。
              红线约束（§6.4）：未确认不处理资金——任何自动补记/冲正必须基于主动查单的
              渠道权威状态，禁止凭账单单方判断直接动账。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Sequence

from web_infra.payment.payment_flow_record import PaymentFlowRecord
from web_infra.payment.payment_flow_status import PaymentFlowEvent, PaymentFlowStatus
from web_infra.payment.payment_flow_store_interface import PaymentFlowStoreInterface
from web_infra.payment.payment_reversal import reversal_flow
from web_infra.payment.payment_status import PaymentStatus, RefundStatus
from web_infra.payment.reconciliation.bill_record import BillRecord
from web_infra.payment.reconciliation.reconciliation_audit_store import (
    ReconciliationAuditRecord,
    ReconciliationAuditStoreInterface,
)
from web_infra.payment.reconciliation.reconciliation_difference import (
    MANUAL_ONLY_TYPES,
    DifferenceType,
    ReconciliationDifference,
)

logger = logging.getLogger("web_infra.payment.reconciliation")


@dataclass
class ReconciliationResult:
    """单轮对账结果（§6.5 对账任务输出）"""

    channel: str = ""  # 渠道名
    biz_date: str = ""  # 账期
    bill_count: int = 0  # 账单明细数
    local_count: int = 0  # 本地流水数
    matched_count: int = 0  # 对齐一致数
    difference_count: int = 0  # 差异数
    difference_types: dict[str, int] = field(default_factory=dict)  # 差异类型分布（§8.6）
    auto_booked: int = 0  # 自动补记数（渠道确认成功，§6.4）
    auto_reversed: int = 0  # 自动冲正数（渠道确认未支付，§6.4）
    manual_count: int = 0  # 人工处理数（金额/状态不一致，P0 告警）
    audit_id: str = ""  # 审计记录号
    differences: list[ReconciliationDifference] = field(default_factory=list)  # 差异清单


class ReconciliationService:
    """对账服务：账单 vs 本地流水对齐、差异分类与自动处理（§6.2/§6.4）"""

    def __init__(
        self,
        flow_store: PaymentFlowStoreInterface,
        audit_store: ReconciliationAuditStoreInterface,
        query_order: Callable[[str], Awaitable[Any]] | None = None,
        query_refund: Callable[[str], Awaitable[Any]] | None = None,
        *,
        auto_handle: bool = True,
    ) -> None:
        """初始化对账服务。

        :param flow_store: 支付流水存储（补记/冲正落库，§5.2）
        :param audit_store: 对账审计存储（§6.6 只增不改）
        :param query_order: 主动查单回调（渠道权威状态，§6.4 未确认不处理资金）；None 时不自动处理
        :param query_refund: 主动查退款回调（退款差异确认，§6.4）；None 时退款差异转人工
        :param auto_handle: 是否启用差异自动处理（查单确认后补记/冲正）；False 仅输出差异清单
        """
        self._flow_store = flow_store
        self._audit_store = audit_store
        self._query_order = query_order
        self._query_refund = query_refund
        self._auto_handle = auto_handle

    async def is_reconciled(self, channel: str, biz_date: str) -> bool:
        """是否已对账（§6.5 防重：同渠道 + 账期已审计 → 跳过本轮）"""
        return await self._audit_store.find_by_channel_and_date(channel, biz_date) is not None

    async def reconcile(
        self,
        bill_records: Sequence[BillRecord],
        local_flows: Sequence[PaymentFlowRecord],
        *,
        channel: str,
        biz_date: str,
    ) -> ReconciliationResult:
        """执行一轮对账（§6.2 流程 3-6）。

        :param bill_records: 渠道账单统一明细（T-1）
        :param local_flows: 本地支付流水快照（调用方按账期查询传入）
        :param channel: 渠道名
        :param biz_date: 账期（YYYY-MM-DD）
        :return: 对账结果（含差异清单与自动处理统计）
        """
        result = ReconciliationResult(channel=channel, biz_date=biz_date,
                                      bill_count=len(bill_records), local_count=len(local_flows))
        local_by_key: dict[tuple[str, str], PaymentFlowRecord] = {
            (f.out_trade_no, f.event_type.value): f for f in local_flows
        }
        bill_by_key: dict[tuple[str, str], BillRecord] = {
            (b.out_trade_no, b.event_type.value): b for b in bill_records
        }
        differences: list[ReconciliationDifference] = []

        # 对齐键 = 订单号 + 事件类型（§6.2 步骤 3）
        for key, bill in bill_by_key.items():
            local = local_by_key.get(key)
            if local is None:
                differences.append(self._channel_only(bill))
                continue
            if local.amount != bill.amount:
                differences.append(self._amount_mismatch(local, bill))
                continue
            if not self._status_matches(local, bill):
                differences.append(self._status_mismatch(local, bill))
                continue
            result.matched_count += 1

        # 本地有、渠道无（含退款差异：退款单方向缺失）
        for key, local in local_by_key.items():
            if key in bill_by_key:
                continue
            if local.event_type == PaymentFlowEvent.REFUND:
                differences.append(self._refund_mismatch(local))
            else:
                differences.append(self._local_only(local))

        # 差异分类统计 + 自动处理（§6.4）
        result.differences = differences
        for diff in differences:
            result.difference_types[diff.diff_type.value] = result.difference_types.get(diff.diff_type.value, 0) + 1
        if self._auto_handle:
            await self._handle_differences(differences, result, channel, biz_date)

        # 审计落库（§6.6 只增不改；防重：同渠道+账期已审计返回首条）
        audit = ReconciliationAuditRecord(
            channel=channel, biz_date=biz_date,
            total_count=result.bill_count, difference_count=result.difference_count,
            difference_types=result.difference_types, differences=differences,
        )
        recorded = await self._audit_store.append(audit)
        result.audit_id = recorded.audit_id
        result.difference_count = len(differences)
        result.manual_count = sum(1 for d in differences if d.diff_type in MANUAL_ONLY_TYPES)
        return result

    # ------------------------------------------------------------------
    # 差异构造（§6.3）
    # ------------------------------------------------------------------

    def _channel_only(self, bill: BillRecord) -> ReconciliationDifference:
        """渠道有、本地无（长款）：查单确认后补记（§6.4）"""
        return ReconciliationDifference(
            diff_type=DifferenceType.CHANNEL_ONLY,
            out_trade_no=bill.out_trade_no, event_type=bill.event_type,
            channel_amount=bill.amount, channel_status=bill.status,
            out_refund_no=bill.out_refund_no, channel_transaction_id=bill.transaction_id,
            action="查单确认后补记/挂账告警（§6.4）",
        )

    def _local_only(self, local: PaymentFlowRecord) -> ReconciliationDifference:
        """本地有、渠道无（短款）：查单确认未支付后冲正（§6.4）"""
        return ReconciliationDifference(
            diff_type=DifferenceType.LOCAL_ONLY,
            out_trade_no=local.out_trade_no, event_type=local.event_type,
            local_amount=local.amount, local_status=local.status.value,
            action="查单确认未支付后冲正/等下期对账（§6.4）",
        )

    def _amount_mismatch(self, local: PaymentFlowRecord, bill: BillRecord) -> ReconciliationDifference:
        """金额不一致（§6.3 极高）：冻结挂账 + P0 告警 + 人工（§6.4 禁止自动动账）"""
        return ReconciliationDifference(
            diff_type=DifferenceType.AMOUNT_MISMATCH,
            out_trade_no=local.out_trade_no, event_type=local.event_type,
            local_amount=local.amount, channel_amount=bill.amount,
            local_status=local.status.value, channel_status=bill.status,
            channel_transaction_id=bill.transaction_id,
            action="冻结挂账 + P0 告警 + 人工介入（§6.4 禁止自动动账）",
        )

    def _status_mismatch(self, local: PaymentFlowRecord, bill: BillRecord) -> ReconciliationDifference:
        """状态不一致（§6.3 高）：P0 告警 + 人工核查（防篡改/渠道异常）"""
        return ReconciliationDifference(
            diff_type=DifferenceType.STATUS_MISMATCH,
            out_trade_no=local.out_trade_no, event_type=local.event_type,
            local_amount=local.amount, channel_amount=bill.amount,
            local_status=local.status.value, channel_status=bill.status,
            channel_transaction_id=bill.transaction_id,
            action="P0 告警 + 人工核查（防篡改/渠道异常，§6.4）",
        )

    def _refund_mismatch(self, local: PaymentFlowRecord) -> ReconciliationDifference:
        """退款差异（§6.3 高，资金流出优先）：查退款确认后补记/告警人工"""
        return ReconciliationDifference(
            diff_type=DifferenceType.REFUND_MISMATCH,
            out_trade_no=local.out_trade_no, event_type=local.event_type,
            local_amount=local.amount, local_status=local.status.value,
            out_refund_no=local.out_refund_no,
            action="查退款确认后补记/告警人工（§6.4 退款差异优先处理）",
        )

    # ------------------------------------------------------------------
    # 自动处理（§6.4：未确认不处理资金）
    # ------------------------------------------------------------------

    async def _handle_differences(self, differences: list[ReconciliationDifference], result: ReconciliationResult,
                                  channel: str, biz_date: str) -> None:
        """差异自动处理：查单/查退款确认渠道权威状态后补记或冲正；无法确认转人工。

        :param channel: 渠道名（本轮回调上下文，参数传递保证并发 reconcile 不串号）
        :param biz_date: 账期（YYYY-MM-DD）
        """
        for diff in differences:
            if diff.diff_type in MANUAL_ONLY_TYPES:
                logger.error("reconciliation_manual_required type=%s out_trade_no=%s（P0 告警：金额/状态不一致，人工介入）", diff.diff_type.value, diff.out_trade_no)
                continue  # 金额/状态不一致：禁止自动动账（§6.4）
            if diff.diff_type == DifferenceType.CHANNEL_ONLY:
                await self._auto_book(diff, result, channel, biz_date)
            elif diff.diff_type == DifferenceType.LOCAL_ONLY:
                await self._auto_reverse(diff, result, channel)
            elif diff.diff_type == DifferenceType.REFUND_MISMATCH:
                await self._auto_refund_book(diff, result, channel, biz_date)

    async def _auto_book(self, diff: ReconciliationDifference, result: ReconciliationResult,
                         channel: str, biz_date: str) -> None:
        """渠道有本地无：主动查单确认渠道已支付 → 补记流水入账（§6.4 补记账，走本地事务表）"""
        if self._query_order is None:
            return
        try:
            order = await self._query_order(diff.out_trade_no)
        except Exception as exc:  # noqa: BLE001 - 查单失败转人工挂账
            logger.error("reconciliation_query_failed out_trade_no=%s err=%s（查单失败，差异转人工）", diff.out_trade_no, exc)
            diff.action = "查单失败，转人工挂账（§6.4）"
            return
        if order is None or getattr(order, "status", None) != PaymentStatus.SUCCESS:
            logger.warning("reconciliation_book_skip out_trade_no=%s（查单确认未支付，不补记，下期对账再核）", diff.out_trade_no)
            diff.action = "查单确认未支付，暂不补记（下期对账再核）"
            return
        # 补记账（§6.4）：走本地事务表写入成功流水（幂等：唯一键兜底）
        channel_amount = diff.channel_amount
        assert channel_amount is not None  # 渠道侧金额必有值（账单来源），此处仅供类型收窄
        await self._flow_store.append(PaymentFlowRecord(
            out_trade_no=diff.out_trade_no, event_type=diff.event_type,
            amount=channel_amount, status=PaymentFlowStatus.BOOKED,
            channel=channel, transaction_id=diff.channel_transaction_id,
            raw={"reconciled": True, "biz_date": biz_date},
        ))
        diff.action = "查单确认渠道已支付，已补记流水（§6.4）"
        diff.handled = True
        result.auto_booked += 1
        logger.info("reconciliation_auto_booked out_trade_no=%s amount=%s（对账补记：回调缺失兜底，§6.6）", diff.out_trade_no, diff.channel_amount)

    async def _auto_reverse(self, diff: ReconciliationDifference, result: ReconciliationResult, channel: str) -> None:
        """本地有渠道无：主动查单确认渠道未支付 → 本地冲正（§6.4/§7.5）"""
        if self._query_order is None:
            return
        try:
            order = await self._query_order(diff.out_trade_no)
        except Exception as exc:  # noqa: BLE001 - 查单失败转人工
            logger.error("reconciliation_query_failed out_trade_no=%s err=%s（查单失败，差异转人工）", diff.out_trade_no, exc)
            diff.action = "查单失败，转人工挂账（§6.4）"
            return
        if order is not None and getattr(order, "status", None) == PaymentStatus.SUCCESS:
            logger.warning("reconciliation_reverse_skip out_trade_no=%s（查单确认已支付，账单时差，等下期对账）", diff.out_trade_no)
            diff.action = "查单确认已支付（账单时差），等下期对账（§6.4）"
            return
        # 渠道确认未支付 → 本地冲正（§7.5：新增反向流水 + 标记原流水）
        await reversal_flow(self._flow_store, await self._find_original(diff), channel=channel, reason=f"对账差异:{diff.diff_type.value}")
        diff.action = "查单确认渠道未支付，已本地冲正（§7.5）"
        diff.handled = True
        result.auto_reversed += 1
        logger.info("reconciliation_auto_reversed out_trade_no=%s（对账冲正：本地误记/未支付，§7.5）", diff.out_trade_no)

    async def _auto_refund_book(self, diff: ReconciliationDifference, result: ReconciliationResult,
                                channel: str, biz_date: str) -> None:
        """退款差异：渠道已退本地未退 → 查退款确认后补记退款流水（§6.4/§7.6 补偿）"""
        if self._query_refund is None or not diff.out_refund_no:
            diff.action = "退款差异转人工核查（§6.4 退款优先）"
            return
        try:
            refund = await self._query_refund(diff.out_refund_no)
        except Exception as exc:  # noqa: BLE001
            logger.error("reconciliation_query_refund_failed out_refund_no=%s err=%s", diff.out_refund_no, exc)
            diff.action = "查退款失败，转人工核查（§6.4）"
            return
        if refund is None or getattr(refund, "status", None) != RefundStatus.SUCCESS:
            diff.action = "查退款确认未成功，转人工核查（§6.4）"
            return
        local_amount = diff.local_amount
        assert local_amount is not None  # 本地侧金额必有值（本地流水来源），此处仅供类型收窄
        await self._flow_store.append(PaymentFlowRecord(
            out_trade_no=diff.out_trade_no, event_type=PaymentFlowEvent.REFUND,
            amount=local_amount, status=PaymentFlowStatus.BOOKED,
            out_refund_no=diff.out_refund_no, channel=channel,
            raw={"reconciled": True, "biz_date": biz_date},
        ))
        diff.action = "查退款确认渠道已退，已补记退款流水（§6.4/§7.6）"
        diff.handled = True
        result.auto_booked += 1
        logger.info("reconciliation_refund_booked out_refund_no=%s（对账补记退款流水，§7.6）", diff.out_refund_no)

    async def _find_original(self, diff: ReconciliationDifference) -> PaymentFlowRecord:
        """按（订单号 + 事件类型）查本地原流水（冲正对象）"""
        flow = await self._flow_store.find_by_order_and_event(diff.out_trade_no, diff.event_type)
        if flow is None:  # pragma: no cover - 差异来源即本地流水，理论不可达
            raise ValueError(f"本地流水不存在，无法冲正：{diff.out_trade_no} {diff.event_type.value}")
        return flow

    @staticmethod
    def _status_matches(local: PaymentFlowRecord, bill: BillRecord) -> bool:
        """本地/账单状态一致判定（§6.3）：本地 BOOKED 对账单 SUCCESS；REVERSED/CLOSED 对账单同口径"""
        if bill.status == "SUCCESS":
            return local.status in (PaymentFlowStatus.BOOKED, PaymentFlowStatus.PENDING)
        return local.status.value == bill.status
