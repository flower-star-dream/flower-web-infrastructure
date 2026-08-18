"""
内存消息队列实现

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 内存消息队列实现（供单体/测试场景使用，规范 §9）。
              同时实现 MessagePublisherInterface 与 MessageConsumerInterface，基于 asyncio.Queue。
              消费失败不再静默丢弃（S9-1）：可重试异常按次数上限指数退避重新入队，
              超限或不可重试（NonRetryableError）投递死信主题（P0-3/S9-7）。
              分区语义（S9-2/规范 §9.2）：按 Message.partition_key 稳定哈希选分区入队，
              单 worker 消费天然保证分区内串行。
              延迟消息（S9-3/规范 §9.5）：到期后二次校验（未被 cancel_delayed 取消）才投递。
              多实例部署应替换为真实 Kafka/RocketMQ 实现。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from web_infra.infra.monitoring.mq_metrics import MqMetrics
from web_infra.capabilities.mq.message import Message, MessageHandler
from web_infra.capabilities.mq.message_consumer_interface import MessageConsumerInterface
from web_infra.capabilities.mq.message_publisher_interface import MessagePublisherInterface
from web_infra.capabilities.mq.message_queue_selector import HashMessageQueueSelector
from web_infra.capabilities.mq.mq_exceptions import NonRetryableError

logger = logging.getLogger("web_infra")


@dataclass
class _DelayedMessage:
    """延迟消息内部包装（不修改 Message 字段，规范 §9.5 到期二次校验）

    记录消息与到期时刻，供到期时校验业务条件（是否被取消）。
    """

    message: Message
    due_at: float  # 到期时刻（time.monotonic() 基准）


class InMemoryMessageQueue(MessagePublisherInterface, MessageConsumerInterface):
    """内存消息队列实现（供单体/测试场景使用）

    @Stateful：进程内内存队列（asyncio.Queue），单实例/单进程部署，多实例需替换为分布式实现（S1-1）。
    同时实现 MessagePublisherInterface 与 MessageConsumerInterface，基于 asyncio.Queue。
    消费失败按异常分类治理：可重试指数退避重新入队，超限或不可重试进死信主题。
    分区语义：按 partition_key 稳定哈希选分区入队（S9-2），单 worker 消费天然保证分区内串行。
    多实例部署应替换为真实 Kafka/RocketMQ 实现。
    """

    def __init__(
        self,
        *,
        dead_letter_topic: str = "web-dlq-topic",
        max_retries: int = 3,
        retry_backoff_seconds: int = 5,
        partition_count: int = 4,
    ) -> None:
        """初始化内存消息队列。

        :param dead_letter_topic: 死信主题（消费失败超限/不可重试时投递，P0-3/S9-7）
        :param max_retries: 消费失败最大重试次数（规范 §9.6）
        :param retry_backoff_seconds: 重试退避基数（秒），指数退避 base * 2^retry_count（S9-4）
        :param partition_count: 分区总数（默认 4），按业务分区键哈希选分区（规范 §9.2）；
                                生产环境按实际队列分区数配置
        """
        self._queue: asyncio.Queue[tuple[int, Message]] = asyncio.Queue()
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._task: asyncio.Task | None = None
        self._dead_letter_topic = dead_letter_topic
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._retry_counts: dict[str, int] = {}  # message_id -> 已重试次数（消息级去重）
        self._partition_count = partition_count
        self._selector = HashMessageQueueSelector()  # 业务分区键稳定哈希选分区（S9-2）
        self._delayed_messages: dict[str, _DelayedMessage] = {}  # message_id -> 延迟消息包装
        self._cancelled: set[str] = set()  # 已取消的延迟消息 id（到期二次校验，S9-3）

    def _partition_of(self, message: Message) -> int:
        """按业务分区键计算消息落区索引（无分区键则落入分区 0）"""
        return self._selector.select(message.topic, message.partition_key, self._partition_count)

    async def publish(self, message: Message) -> str:
        """发送消息：按业务分区键哈希选分区后入队（规范 §9.2 分区内串行）"""
        await self._queue.put((self._partition_of(message), message))
        MqMetrics.record_published(message.topic)
        return message.message_id

    async def send_delay(self, message: Message, delay_seconds: int | float) -> str:
        """发送延迟消息：定时后投递（规范 §9.5/S9-3）

        到期执行二次校验：业务侧可调用 cancel_delayed 取消未到期延迟消息，
        防止过期消息被消费（延迟到期后检查 message_id 是否在取消集合，在则丢弃）。
        """
        envelope = _DelayedMessage(message=message, due_at=time.monotonic() + delay_seconds)
        self._delayed_messages[message.message_id] = envelope
        asyncio.create_task(self._delayed_dispatch(message.message_id, delay_seconds))
        return message.message_id

    async def _delayed_dispatch(self, message_id: str, delay_seconds: float) -> None:
        """延迟到期回调：到期二次校验（未被取消）后按分区入队投递（S9-3）"""
        await asyncio.sleep(delay_seconds)
        envelope = self._delayed_messages.pop(message_id, None)
        if envelope is None:
            return  # 已被取消清理或重复到期，直接丢弃
        if message_id in self._cancelled:
            # 到期二次校验：业务侧已取消该延迟消息，丢弃不投递，防止过期消息被消费
            self._cancelled.discard(message_id)
            logger.info(
                "delayed_message_cancelled message_id=%s topic=%s",
                message_id, envelope.message.topic,
            )
            return
        await self._queue.put((self._partition_of(envelope.message), envelope.message))
        MqMetrics.record_published(envelope.message.topic)

    def cancel_delayed(self, message_id: str) -> bool:
        """取消未到期的延迟消息（到期二次校验，规范 §9.5）

        :param message_id: 待取消的延迟消息 ID
        :return: 是否成功取消（消息仍在延迟期内才返回 True，已到期投递/不存在返回 False）
        """
        if message_id in self._delayed_messages:
            self._cancelled.add(message_id)
            return True
        return False

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        """订阅主题并注册处理器"""
        self._handlers.setdefault(topic, []).append(handler)

    async def start(self) -> None:
        """启动消费循环"""
        if self._task is None:
            self._task = asyncio.create_task(self._dispatch_loop())

    async def stop(self) -> None:
        """停止消费循环"""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _dispatch_loop(self) -> None:
        """消费循环：取出消息分发给订阅者，失败按异常分类治理（不静默丢弃，S9-1）

        分区语义：队列元素为 (partition_index, Message)，publish 时已按业务分区键哈希
        选分区入队；单 worker 消费天然保证分区内串行（规范 §9.2）——
        同一分区的消息按入队顺序依次处理，不会被并发消费。
        """
        while True:
            _, message = await self._queue.get()
            last_exc: Exception | None = None
            for handler in self._handlers.get(message.topic, []):
                try:
                    await handler(message)
                except Exception as exc:  # noqa: BLE001 - 汇聚异常统一治理
                    last_exc = exc
            if last_exc is None:
                # 消费成功：清理该消息的退避重试计数，防止曾失败过又成功的 message_id
                # 永久驻留 _retry_counts 导致内存无限增长
                self._retry_counts.pop(message.message_id, None)
                MqMetrics.record_consumed(message.topic)
                continue
            MqMetrics.record_error(message.topic, "consume")
            if isinstance(last_exc, NonRetryableError):
                # 不可重试：直接进死信（P0-3/S9-7）
                await self._send_to_dlq(message, last_exc, retry_count=0)
            else:
                await self._retry_or_dlq(message, last_exc)

    async def _retry_or_dlq(self, message: Message, exc: Exception) -> None:
        """可重试异常：指数退避重新入队；超过上限进死信（S9-1）"""
        retries = self._retry_counts.get(message.message_id, 0) + 1
        if retries <= self._max_retries:
            self._retry_counts[message.message_id] = retries
            delay = self._retry_backoff_seconds * (2 ** (retries - 1))
            logger.warning(
                "message_retry_scheduled message_id=%s topic=%s retry=%s delay=%ss",
                message.message_id, message.topic, retries, delay,
            )
            asyncio.create_task(self._requeue_after(message, delay))
            return
        self._retry_counts.pop(message.message_id, None)
        await self._send_to_dlq(message, exc, retry_count=retries - 1)

    async def _requeue_after(self, message: Message, delay: float) -> None:
        """延迟重新入队（指数退避到期后再次分发，按业务分区键选分区保持分区内串行）"""
        await asyncio.sleep(delay)
        await self._queue.put((self._partition_of(message), message))

    async def _send_to_dlq(self, message: Message, exc: Exception, *, retry_count: int) -> None:
        """投递死信主题：死信消息包裹原始消息信息（P0-3/S9-7），并记录死信指标"""
        dlq_message = Message(
            topic=self._dead_letter_topic,
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
        await self._queue.put((self._partition_of(dlq_message), dlq_message))
        MqMetrics.record_dlq(self._dead_letter_topic)
        logger.error(
            "message_consume_dlq message_id=%s topic=%s dlq_topic=%s error=%s",
            message.message_id, message.topic, self._dead_letter_topic, exc,
        )

    def update_metrics(self) -> None:
        """刷新消息队列推送式指标（队列积压，供 /metrics 抓取调用）"""
        MqMetrics.update_pending("memory", self._queue.qsize())
