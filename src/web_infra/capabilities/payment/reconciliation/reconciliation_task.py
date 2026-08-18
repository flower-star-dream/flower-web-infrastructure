"""
对账定时任务（run_reconciliation）

@Author: 花海
@Date: 2026/08/17
@Description: 对账任务函数（规范 §6.5）：T+1 对账编排入口——全局唯一标识
              `pay:job:reconcile:{channel}:{biz_date}`（对齐上位 §23.1 任务定义），
              分布式防重（同渠道 + 账期已审计 → 跳过，§6.5/§6.6），
              由调用方注册到框架 TaskScheduler 定时执行；重试幂等（同一账期只对账一次）。
              与流水表清理任务分离配置、独立运行（§6.5）。
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Sequence

from web_infra.capabilities.payment.payment_flow_record import PaymentFlowRecord
from web_infra.capabilities.payment.reconciliation.bill_record import BillRecord
from web_infra.capabilities.payment.reconciliation.reconciliation_service import ReconciliationResult, ReconciliationService

logger = logging.getLogger("web_infra.capabilities.payment.reconciliation")

# 对账任务唯一标识模板（§6.5：pay:job:reconcile:{channel}:{biz_date}，模块归属 + 账期）
RECONCILE_JOB_ID_TEMPLATE = "pay:job:reconcile:{channel}:{biz_date}"


async def run_reconciliation(
    service: ReconciliationService,
    *,
    channel: str,
    biz_date: str,
    bill_provider: Callable[[], Awaitable[Sequence[BillRecord]]],
    flow_provider: Callable[[], Awaitable[Sequence[PaymentFlowRecord]]],
) -> ReconciliationResult | None:
    """执行一轮 T+1 对账（§6.5：防重 + 数据拉取 + 对账编排）。

    :param service: 对账服务（差异分类与自动处理，§6.2）
    :param channel: 渠道名
    :param biz_date: 账期（YYYY-MM-DD，T-1）
    :param bill_provider: 渠道账单拉取回调（下载 + 解析为统一明细，§6.2 步骤 1-2；失败抛异常由调度重试）
    :param flow_provider: 本地支付流水查询回调（按账期查本地流水，§5.2）
    :return: 对账结果；已对账（防重，§6.5）返回 None
    """
    job_id = RECONCILE_JOB_ID_TEMPLATE.format(channel=channel, biz_date=biz_date)
    # 分布式防重（§6.5/§6.6）：同渠道 + 账期已审计 → 本轮跳过（重试幂等）
    if await service.is_reconciled(channel, biz_date):
        logger.info("reconciliation_skip_duplicated job_id=%s（同账期已对账，防重跳过）", job_id)
        return None
    bill_records = await bill_provider()
    local_flows = await flow_provider()
    result = await service.reconcile(bill_records, local_flows, channel=channel, biz_date=biz_date)
    logger.info(
        "reconciliation_done job_id=%s bill=%s local=%s matched=%s diff=%s auto_booked=%s auto_reversed=%s manual=%s",
        job_id, result.bill_count, result.local_count, result.matched_count,
        result.difference_count, result.auto_booked, result.auto_reversed, result.manual_count,
    )
    return result
