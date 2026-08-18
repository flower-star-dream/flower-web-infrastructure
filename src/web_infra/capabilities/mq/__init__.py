"""
消息队列模块

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 消息队列统一抽象接口与实现聚合导出，遵循规范 §9（消息队列规范）与 §5.8（消息常量）。
              消息体包含 code 字段（§4.5.4 异步链路错误码传递）；
              消费者异常禁止静默吞没（§16.4），按异常分类重试/死信治理（S9-1/P0-3/S9-7）；
              Outbox 支持指数退避重试与死信队列（S9-4）。
"""
from web_infra.infra.constants.infra_constant import InfraConstant
from web_infra.capabilities.mq.mq_config import MqConfig
from web_infra.capabilities.mq.mq_exceptions import RetryableError, NonRetryableError
from web_infra.capabilities.mq.message import Message, MessageHandler, generate_message_id
from web_infra.capabilities.mq.message_publisher_interface import MessagePublisherInterface
from web_infra.capabilities.mq.message_consumer_interface import MessageConsumerInterface
from web_infra.capabilities.mq.in_memory_message_queue import InMemoryMessageQueue
from web_infra.capabilities.mq.rocketmq_config import RocketMqConfig
from web_infra.capabilities.mq.rocketmq_publisher import RocketMqPublisher
from web_infra.capabilities.mq.message_queue_registry import MessageQueueRegistry
from web_infra.capabilities.mq.message_idempotency_store_interface import MessageIdempotencyStoreInterface
from web_infra.capabilities.mq.in_memory_message_idempotency_store import InMemoryMessageIdempotencyStore
from web_infra.capabilities.mq.redis_message_idempotency_store import RedisMessageIdempotencyStore
from web_infra.capabilities.mq.idempotent_consumer import IdempotentConsumer
from web_infra.capabilities.mq.retryable_consumer import RetryableConsumer
from web_infra.capabilities.mq.outbox import (
    OutboxStatus,
    OutboxRecord,
    OutboxStoreInterface,
    InMemoryOutboxStore,
    MysqlOutboxStore,
    OutboxPublisher,
    OutboxCleaner,
    DlqConsumer,
    requeue_dlq_to_outbox,
    register_outbox_tasks,
)

# 消息常量（统一管理于 web_infra.infra.constants，此处转发导出保持兼容）
INFRA_MQ_TOPIC_ORDER = InfraConstant.INFRA_MQ_TOPIC_ORDER
INFRA_MQ_TAG_ORDER_PAY = InfraConstant.INFRA_MQ_TAG_ORDER_PAY
INFRA_MQ_GROUP_ORDER_PAY = InfraConstant.INFRA_MQ_GROUP_ORDER_PAY

__all__ = [
    "MqConfig",
    "RetryableError",
    "NonRetryableError",
    "Message",
    "MessagePublisherInterface",
    "MessageConsumerInterface",
    "MessageHandler",
    "InMemoryMessageQueue",
    "generate_message_id",
    "INFRA_MQ_TOPIC_ORDER",
    "INFRA_MQ_TAG_ORDER_PAY",
    "INFRA_MQ_GROUP_ORDER_PAY",
    "RocketMqConfig",
    "RocketMqPublisher",
    "MessageQueueRegistry",
    "MessageIdempotencyStoreInterface",
    "InMemoryMessageIdempotencyStore",
    "RedisMessageIdempotencyStore",
    "IdempotentConsumer",
    "RetryableConsumer",
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
