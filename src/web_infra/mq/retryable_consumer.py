"""
消息消费异常分类重试封装

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 消息消费异常分类治理封装（规范 §9.1/S9-1）：区分可重试（网络/超时类，RetryableError
              或普通异常）与不可重试（业务校验失败类，NonRetryableError）异常；
              可重试按次数上限指数退避重试（base * 2^attempt），超过上限或不可重试
              投递死信队列（P0-3/S9-7，复用 MqConfig.dead_letter_topic）。
              与 IdempotentConsumer 组合使用：业务失败回滚幂等键后可安全重试。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from web_infra.monitoring.mq_metrics import MqMetrics
from web_infra.mq.message import Message, MessageHandler
from web_infra.mq.mq_exceptions import NonRetryableError

logger = logging.getLogger("web_infra.mq.retryable_consumer")


class RetryableConsumer:
    """消息消费异常分类重试封装（可重试指数退避，超限或不可重试进 DLQ）"""

    def __init__(
        self,
        dlq_publisher: Any,
        *,
        max_retries: int = 3,
        retry_backoff_seconds: int = 5,
        dlq_topic: str = "web-dlq-topic",
    ) -> None:
        """初始化重试消费封装。

        :param dlq_publisher: 死信发布者（MessagePublisherInterface，用于投递死信主题）
        :param max_retries: 可重试异常最大重试次数（规范 §9.6，默认 3）
        :param retry_backoff_seconds: 重试退避基数（秒），指数退避 base * 2^attempt（S9-4）
        :param dlq_topic: 死信主题（与 MqConfig.dead_letter_topic 对齐，P0-3/S9-7）
        """
        self._dlq_publisher = dlq_publisher
        self._max_retries = max_retries
        self._backoff_seconds = retry_backoff_seconds
        self._dlq_topic = dlq_topic

    async def consume(self, message: Message, handler: MessageHandler) -> bool:
        """消费一条消息：异常分类治理（可重试指数退避重试，超限或不可重试进 DLQ）。

        :param message: 统一消息
        :param handler: 业务处理函数（建议包一层 IdempotentConsumer.consume 保证幂等）
        :return: True 表示业务成功；False 表示已进入死信队列（不可重试或重试超限）
        """
        for attempt in range(self._max_retries):
            try:
                await handler(message)
                return True
            except NonRetryableError as exc:
                await self._send_to_dlq(message, exc, retry_count=attempt + 1)
                return False
            except Exception as exc:  # noqa: BLE001 - 可重试异常（网络/超时等临时故障）
                if attempt + 1 >= self._max_retries:
                    await self._send_to_dlq(message, exc, retry_count=attempt + 1)
                    return False
                delay = self._backoff_seconds * (2 ** attempt)
                logger.warning(
                    "message_consume_retry message_id=%s topic=%s attempt=%s delay=%ss error=%s",
                    message.message_id, message.topic, attempt + 1, delay, exc,
                )
                await asyncio.sleep(delay)
        return False  # 不可达（循环内已 return）

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _send_to_dlq(self, message: Message, exc: Exception, *, retry_count: int) -> None:
        """投递死信主题：包裹原始消息信息（P0-3/S9-7）"""
        dlq_message = Message(
            topic=self._dlq_topic,
            tag=message.tag,
            body={
                "original_msg_id": message.message_id,
                "original_topic": message.topic,
                "biz_id": str(message.body.get("biz_id") or message.message_id),
                "retry_count": retry_count,
                "error": str(exc),
                "payload": message.body,
            },
        )
        try:
            await self._dlq_publisher.publish(dlq_message)
        except Exception:  # noqa: BLE001 - 死信投递失败不阻塞调用方，留日志人工介入
            logger.exception("dlq_publish_failed message_id=%s dlq_topic=%s", message.message_id, self._dlq_topic)
        else:
            MqMetrics.record_dlq(self._dlq_topic)
        logger.error(
            "message_consume_dlq message_id=%s topic=%s retry_count=%s error=%s",
            message.message_id, message.topic, retry_count, exc,
        )
