"""
Outbox 轮询投递发布器

@Author: 花海
@Date: 2026/08/14 19:00
@Description: Outbox 轮询投递（规范 §21.3：定时扫描待发送消息投递到 MQ，投递成功更新状态，
              失败按指数退避设置 next_retry_at（S9-4），重试超限投递死信主题并置死信状态（P0-3/S9-7））。
              投递成功后依赖 Broker 确认（§9.8 confirm/ack），未确认视为失败重试。
              轮询调度遵守 §23 防重复执行（多实例配分布式锁）。
              MqConfig.max_retry / retry_backoff_seconds / dead_letter_topic 在此实际使用。
"""
from __future__ import annotations

import logging
from typing import Any

from web_infra.infra.monitoring.mq_metrics import MqMetrics
from web_infra.capabilities.mq.message import Message
from web_infra.capabilities.mq.mq_config import MqConfig

logger = logging.getLogger("web_infra.capabilities.mq.outbox")


class OutboxPublisher:
    """Outbox 轮询投递发布器（指数退避重试，重试超限进死信队列）"""

    def __init__(
        self,
        store: Any,
        publisher: Any,
        *,
        batch_size: int = 100,
        max_retries: int | None = None,
        config: MqConfig | None = None,
    ) -> None:
        """初始化发布器。

        :param store: Outbox 存储（OutboxStoreInterface）
        :param publisher: 消息发布者（MessagePublisherInterface，规范 §9.8 依赖 Broker 确认）
        :param batch_size: 单轮投递条数上限
        :param max_retries: 投递重试上限（显式传入优先于 config.max_retry；默认 5，规范 §9.6）
        :param config: 消息队列配置（MqConfig.max_retry / retry_backoff_seconds / dead_letter_topic 生效）
        """
        self._store = store
        self._publisher = publisher
        self._batch_size = batch_size
        self._config = config or MqConfig()
        self._max_retries = max_retries if max_retries is not None else self._config.max_retry
        self._backoff_seconds = self._config.retry_backoff_seconds  # 指数退避基数（S9-4）
        self._dlq_topic = self._config.dead_letter_topic  # 死信主题（P0-3/S9-7）

    async def publish_pending(self) -> int:
        """轮询并投递待发送消息（退避到期记录），返回投递成功条数。

        投递失败：按指数退避设置 next_retry_at；重试超限投递死信主题并置死信状态。
        """
        records = await self._store.next_pending(self._batch_size)
        sent = 0
        for record in records:
            message = Message(
                message_id=record.msg_id,
                topic=record.topic,
                tag=record.tag,
                body=record.payload,
            )
            try:
                await self._publisher.publish(message)
            except Exception as exc:  # noqa: BLE001 - 投递失败统一走退避重试/死信治理
                await self._handle_failure(record, exc)
            else:
                await self._store.mark_sent(record.msg_id)
                sent += 1
        return sent

    # ------------------------------------------------------------------
    # 内部：失败治理（指数退避 -> 重试超限进死信）
    # ------------------------------------------------------------------

    async def _handle_failure(self, record: Any, exc: Exception) -> None:
        """投递失败治理：未超限按指数退避调度下次重试；超限投递死信并置死信状态（S9-4/P0-3）"""
        retries = record.retry_count + 1
        if retries >= self._max_retries:
            # 重试超限：先置失败超限（retry_count 收敛），投递死信主题后置死信状态（P0-3/S9-7）
            await self._store.mark_failed(record.msg_id, self._max_retries, retry_delay_seconds=None)
            await self._send_to_dlq(record, exc, retry_count=retries)
            await self._store.mark_dlq(record.msg_id)
        else:
            # 指数退避：base * 2^retry_count（首次失败 retry_count=0 -> base，S9-4）
            delay = self._backoff_seconds * (2 ** record.retry_count)
            await self._store.mark_failed(record.msg_id, self._max_retries, retry_delay_seconds=delay)
        logger.error(
            "outbox_publish_failed msg_id=%s topic=%s retry_count=%s error=%s",
            record.msg_id, record.topic, retries, exc,
        )

    async def _send_to_dlq(self, record: Any, exc: Exception, *, retry_count: int) -> None:
        """投递死信主题：死信消息包裹原始消息信息（original_msg_id/original_topic/biz_id/payload）"""
        dlq_message = Message(
            topic=self._dlq_topic,
            tag=record.tag,
            body={
                "original_msg_id": record.msg_id,
                "original_topic": record.topic,
                "biz_id": record.biz_id,
                "retry_count": retry_count,
                "error": str(exc),
                "payload": record.payload,
            },
        )
        try:
            await self._publisher.publish(dlq_message)
        except Exception:  # noqa: BLE001 - 死信投递失败不阻塞状态流转，留日志人工介入
            logger.exception("outbox_dlq_publish_failed msg_id=%s dlq_topic=%s", record.msg_id, self._dlq_topic)
        else:
            MqMetrics.record_dlq(self._dlq_topic)
