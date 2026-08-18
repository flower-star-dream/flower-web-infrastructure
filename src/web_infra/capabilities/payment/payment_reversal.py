"""
支付冲正（reversal_flow）

@Author: 花海
@Date: 2026/08/17
@Description: 冲正流程（规范 §7.5）：对"不应发生或状态未知"的本地记账做反向调整——
              新增反向冲正流水（不可删除原流水），标记原流水为已冲正，账务做反向调整。
              触发条件约束：只适用支付后阶段（§7.1 阶段三），必须基于渠道权威状态
              （主动查单/对账结论，§6.4），禁止凭猜测冲正。
              幂等：以「原流水号 + REVERSAL」唯一索引兜底（flow_store.find_reversal），
              重复执行返回首次冲正流水。
              冲正事件钩子：下游业务补偿（扣回余额/回收积分）由调用方经 event_callback 投递
              （建议走消息表 §5.4，下游补偿失败不得阻塞冲正流水本身，§7.5）。
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Awaitable, Callable

from web_infra.capabilities.payment.payment_flow_record import PaymentFlowRecord
from web_infra.capabilities.payment.payment_flow_status import PaymentFlowEvent, PaymentFlowStatus
from web_infra.capabilities.payment.payment_flow_store_interface import PaymentFlowStoreInterface

logger = logging.getLogger("web_infra.capabilities.payment.reversal")


async def reversal_flow(
    flow_store: PaymentFlowStoreInterface,
    original_flow: PaymentFlowRecord,
    *,
    channel: str = "",
    reason: str = "",
    event_callback: Callable[[PaymentFlowRecord], Awaitable[None]] | None = None,
    session: Any | None = None,
) -> PaymentFlowRecord:
    """执行冲正：新增反向冲正流水（幂等，§7.5）+ 可选冲正事件回调（业务补偿）。

    :param flow_store: 支付流水存储（本地事务表，§5.2）
    :param original_flow: 被冲正的原流水（须已入账 BOOKED，本地误记/渠道确认未支付）
    :param channel: 渠道名（冲正流水记录，审计维度）
    :param reason: 冲正原因（对账差异/人工核查，审计留痕）
    :param event_callback: 冲正事件回调（下游业务补偿投递，建议走消息表；失败仅记日志不阻塞，§7.5）
    :param session: 业务事务会话（可选，同事务写入）
    :return: 冲正流水（重复执行返回首次记录，幂等）
    :raises ValueError: 原流水已是冲正流水或已被冲正
    """
    # 幂等（§7.5）：原流水已存在冲正流水 → 返回首次结果
    existing = await flow_store.find_reversal(original_flow.flow_id)
    if existing is not None:
        return existing

    # 防误用（§7.5 红线）：冲正对象必须是正常入账流水（禁止冲正冲正流水）
    if original_flow.is_reversal:
        raise ValueError(f"禁止冲正冲正流水：{original_flow.flow_id}（§7.5 红线）")
    if original_flow.status == PaymentFlowStatus.REVERSED:
        raise ValueError(f"原流水已被冲正：{original_flow.flow_id}（§7.5 幂等）")

    # 新增反向冲正流水（不可删除原流水，§7.5）：amount 沿用原金额（反向语义由 is_reversal 表达）
    reversal = PaymentFlowRecord(
        out_trade_no=original_flow.out_trade_no,
        event_type=PaymentFlowEvent.REVERSAL,
        amount=original_flow.amount,
        status=PaymentFlowStatus.REVERSED,
        out_refund_no=original_flow.out_refund_no,
        original_flow_id=original_flow.flow_id,
        is_reversal=True,
        reversed_at=datetime.now(),
        currency=original_flow.currency,
        channel=channel or original_flow.channel,
        transaction_id=original_flow.transaction_id,
        raw={"reason": reason, "original_flow_id": original_flow.flow_id},
    )
    recorded = await flow_store.append(reversal, session=session)
    # 标记原流水已冲正（存储实现内聚行为：append REVERSAL 时自动置原流水 REVERSED/reversed_at）
    logger.info(
        "payment_reversal flow_id=%s original_flow_id=%s out_trade_no=%s amount=%s reason=%s",
        recorded.flow_id, original_flow.flow_id, original_flow.out_trade_no, original_flow.amount, reason,
    )
    # 冲正事件（§7.5 业务补偿）：下游补偿失败不得阻塞冲正流水本身，仅记日志告警人工
    if event_callback is not None:
        try:
            await event_callback(recorded)
        except Exception as exc:  # noqa: BLE001 - 下游补偿失败不阻塞冲正
            logger.error(
                "payment_reversal_event_failed flow_id=%s out_trade_no=%s err=%s（下游补偿失败，进入独立补偿队列人工介入）",
                recorded.flow_id, original_flow.out_trade_no, exc,
            )
    return recorded
