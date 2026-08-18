"""
Outbox 本地事务表模块

@Author: 花海
@Date: 2026/08/14 19:00
@Description: Outbox 本地事务表（规范 §21.3 / §9.8 最终一致性可靠投递）：
              业务本地事务内写业务数据 + 追加 Outbox 消息，轮询投递到 MQ，
              投递成功更新状态，失败指数退避重试（S9-4），重试超限投递死信队列（P0-3/S9-7）；
              已发送记录 7 天后清理。提供内存/MySQL 双存储实现与死信消费治理。
"""
from web_infra.capabilities.mq.outbox.outbox_status import OutboxStatus
from web_infra.capabilities.mq.outbox.outbox_record import OutboxRecord
from web_infra.capabilities.mq.outbox.outbox_store_interface import OutboxStoreInterface
from web_infra.capabilities.mq.outbox.in_memory_outbox_store import InMemoryOutboxStore
from web_infra.capabilities.mq.outbox.mysql_outbox_store import MysqlOutboxStore
from web_infra.capabilities.mq.outbox.outbox_publisher import OutboxPublisher
from web_infra.capabilities.mq.outbox.outbox_cleaner import OutboxCleaner
from web_infra.capabilities.mq.outbox.dlq_consumer import DlqConsumer, requeue_dlq_to_outbox
from web_infra.capabilities.mq.outbox.outbox_task_registrar import register_outbox_tasks

__all__ = [
    "OutboxStatus",
    "OutboxRecord",
    "OutboxStoreInterface",
    "InMemoryOutboxStore",
    "MysqlOutboxStore",
    "OutboxPublisher",
    "OutboxCleaner",
    "DlqConsumer",
    "requeue_dlq_to_outbox",
    "register_outbox_tasks",
]
