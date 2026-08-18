"""
死信队列消费者

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 死信队列消费者（规范 P0-3/S9-7 红线级：重试超限或不可重试的消息必须进入 DLQ 并被消费治理）。
              订阅死信主题，默认记录日志 + 死信指标告警；提供 on_dlq 钩子实现
              重投递回 Outbox（requeue_dlq_to_outbox）或丢弃策略，供人工/自动修复后重放。
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from web_infra.infra.monitoring.mq_metrics import MqMetrics
from web_infra.capabilities.mq.message import Message
from web_infra.capabilities.mq.outbox.outbox_record import OutboxRecord

logger = logging.getLogger("web_infra.capabilities.mq.outbox.dlq")

# 死信处理钩子类型：接收死信消息，异步执行重投递/丢弃等治理动作
DlqHandler = Callable[[Message], Awaitable[None]]


class DlqConsumer:
    """死信队列消费者（订阅死信主题，记录/告警并提供重投递或丢弃钩子）"""

    def __init__(
        self,
        consumer: Any,
        *,
        dlq_topic: str = "web-dlq-topic",
        on_dlq: DlqHandler | None = None,
    ) -> None:
        """初始化死信消费者。

        :param consumer: 消息消费者（MessageConsumerInterface，支持 subscribe/start/stop）
        :param dlq_topic: 死信主题（与 MqConfig.dead_letter_topic 对齐，默认 web-dlq-topic）
        :param on_dlq: 死信处理钩子（默认记录日志 + 死信指标；可传入 requeue_dlq_to_outbox
            或自定义丢弃策略）
        """
        self._consumer = consumer
        self._dlq_topic = dlq_topic
        self._on_dlq = on_dlq or self._default_on_dlq

    async def start(self) -> None:
        """订阅死信主题并启动消费"""
        self._consumer.subscribe(self._dlq_topic, self._handle)
        await self._consumer.start()

    async def stop(self) -> None:
        """停止消费"""
        await self._consumer.stop()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _handle(self, message: Message) -> None:
        """收到死信消息：记录指标与日志，交给治理钩子"""
        MqMetrics.record_dlq(message.topic)
        logger.error(
            "dlq_message_received topic=%s message_id=%s original_topic=%s",
            message.topic, message.message_id, message.body.get("original_topic", ""),
        )
        await self._on_dlq(message)

    @staticmethod
    async def _default_on_dlq(message: Message) -> None:
        """默认死信治理：仅记录日志（由运维/监控告警介入，不自动重放避免风暴）"""
        logger.error(
            "dlq_message_discarded topic=%s message_id=%s body=%s",
            message.topic, message.message_id, message.body,
        )


async def requeue_dlq_to_outbox(store: Any, message: Message) -> Any:
    """把死信消息重投递回 Outbox（新 OutboxRecord，状态重置待发送，可再次轮询投递）。

    :param store: Outbox 存储（OutboxStoreInterface）
    :param message: 死信消息（body 含 original_msg_id/original_topic/biz_id/payload）
    :return: 新追加的 OutboxRecord（topic 回落到原始业务主题，恢复投递）
    """
    body = message.body if isinstance(message.body, dict) else {}
    record = OutboxRecord(
        topic=str(body.get("original_topic") or ""),
        biz_id=str(body.get("biz_id") or ""),
        payload=dict(body.get("payload") or {}),
        tag=message.tag,
    )
    if not record.topic:
        raise ValueError("死信消息缺少 original_topic，无法重投递回 Outbox")
    logger.warning("dlq_requeue_to_outbox original_msg_id=%s topic=%s", body.get("original_msg_id", ""), record.topic)
    return await store.append(record)
