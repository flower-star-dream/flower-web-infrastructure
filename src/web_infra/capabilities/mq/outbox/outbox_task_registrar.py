"""
Outbox 定时任务装配工具

@Author: 花海
@Date: 2026/08/15 10:00
@Description: Outbox 轮询投递与清理定时任务装配入口（规范 §21.3/S21-2，任务命名含模块归属
              message-outbox-publish / message-outbox-cleanup）。
              轻量工具函数：业务应用创建 TaskScheduler 后调用 register_outbox_tasks 即可注册，
              默认不启用（由业务 yml 配置开关决定是否调用），不侵入 Application 装配。
"""
from __future__ import annotations

import logging
from typing import Any

from web_infra.capabilities.mq.mq_config import MqConfig
from web_infra.capabilities.mq.outbox.outbox_cleaner import OutboxCleaner
from web_infra.capabilities.mq.outbox.outbox_publisher import OutboxPublisher

logger = logging.getLogger("web_infra.capabilities.mq.outbox")

# 任务命名（规范 §21.3：命名含模块归属与动作语义）
TASK_PUBLISH = "message-outbox-publish"
TASK_CLEANUP = "message-outbox-cleanup"


def register_outbox_tasks(
    scheduler: Any,
    store: Any,
    publisher: Any,
    *,
    config: MqConfig | None = None,
    cleaner: Any | None = None,
    publish_interval_seconds: float = 5.0,
    cleanup_interval_seconds: float = 3600.0,
    batch_size: int = 100,
    retain_days: int = 7,
) -> list[str]:
    """注册 Outbox 轮询投递与清理定时任务（S21-2，默认不启用，由调用方决定）。

    :param scheduler: 定时任务调度器（TaskScheduler，规范 §23 支持分布式锁防重复执行）
    :param store: Outbox 存储（OutboxStoreInterface）
    :param publisher: 消息发布者（MessagePublisherInterface）
    :param config: 消息队列配置（max_retry / retry_backoff_seconds / dead_letter_topic 生效）
    :param cleaner: 清理器（缺省按 retain_days 构建 OutboxCleaner）
    :param publish_interval_seconds: 轮询投递间隔（秒）
    :param cleanup_interval_seconds: 清理间隔（秒）
    :param batch_size: 单轮投递条数上限
    :param retain_days: 已发送记录保留天数（规范 §21.3，默认 7 天）
    :return: 已注册任务名列表
    """
    cfg = config or MqConfig()
    outbox_publisher = OutboxPublisher(store, publisher, config=cfg, batch_size=batch_size)
    outbox_cleaner = cleaner or OutboxCleaner(store, retain_days=retain_days)

    scheduler.register_task(
        name=TASK_PUBLISH,
        module="mq.outbox",
        interval_seconds=publish_interval_seconds,
        handler=outbox_publisher.publish_pending,
        description="Outbox 轮询投递（指数退避重试，重试超限进死信队列）",
    )
    scheduler.register_task(
        name=TASK_CLEANUP,
        module="mq.outbox",
        interval_seconds=cleanup_interval_seconds,
        handler=outbox_cleaner.cleanup,
        description="Outbox 已发送记录清理（保留期外归档删除）",
    )
    logger.info("outbox_tasks_registered publish=%s cleanup=%s", TASK_PUBLISH, TASK_CLEANUP)
    return [TASK_PUBLISH, TASK_CLEANUP]
