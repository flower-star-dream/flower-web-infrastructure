"""
支付订单超时自动关单任务

@Author: 花海
@Date: 2026/08/16
@Description: 支付订单超时收敛（规范 §5.5）：扫描超时未支付订单 → 渠道 close_order 骨架
              （内部先查单确认未支付）→ 本地状态置 CLOSED + 关单流水。
              查单失败/渠道异常跳过该订单并记 WARN（禁止在渠道状态不明时强行关单，防已支付被关闭），
              跳过单进入下轮重试。业务通过框架 TaskScheduler 注册定时任务（唯一标识、防重，§23）。
"""
from __future__ import annotations

import logging
from datetime import datetime

from web_infra.monitoring.payment_metrics import record_close
from web_infra.payment.payment_channel_template import PaymentChannelTemplate
from web_infra.payment.payment_order_store_interface import PaymentOrderStoreInterface
from web_infra.payment.payment_status import PaymentStatus

logger = logging.getLogger("web_infra.payment.close_task")


async def close_expired_orders(
    order_store: PaymentOrderStoreInterface,
    channel: PaymentChannelTemplate,
    expire_before: datetime,
    limit: int = 100,
) -> int:
    """扫描并关闭超时未支付订单（§5.5 定时关单）。

    :param order_store: 本地支付订单存储（查超时订单 + 更新状态）
    :param channel: 渠道骨架实现（close_order 内部先查单确认未支付）
    :param expire_before: 失效判定时间（早于该时间的未支付订单视为超时）
    :param limit: 单轮扫描上限
    :return: 成功关闭的订单数
    """
    expired_orders = await order_store.find_expired(expire_before, limit)
    closed = 0
    channel_name = channel.__class__.__name__
    for order in expired_orders:
        try:
            # 骨架 close_order：本地幂等 + 查单确认未支付 + 渠道关单 + 关单流水
            await channel.close_order(order.out_trade_no)
            await order_store.update_status(order.out_trade_no, PaymentStatus.CLOSED)
            closed += 1
            record_close(channel_name, "closed")
            logger.info("payment_order_closed out_trade_no=%s", order.out_trade_no)
        except Exception as exc:  # noqa: BLE001 - 查单失败/渠道异常：跳过不强行关单（§5.5）
            record_close(channel_name, "skipped")
            logger.warning(
                "payment_close_skipped out_trade_no=%s err=%s（查单失败禁止强行关单，下轮重试）",
                order.out_trade_no, exc,
            )
    return closed
