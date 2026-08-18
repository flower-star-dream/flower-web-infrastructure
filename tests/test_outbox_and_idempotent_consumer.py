"""
消息幂等消费 + Outbox 单元测试

@Author: 花海
@Date: 2026/08/14 19:00
@Description: 验证消息幂等消费（bizId+msgId 去重/失败回滚）与 Outbox
              （追加->投递->状态流转、重试超限、清理，规范 §9.2/§9.6/§21.3）。
"""
from datetime import datetime, timedelta, timezone

import pytest

from web_infra.capabilities.mq import (
    IdempotentConsumer,
    InMemoryMessageIdempotencyStore,
    InMemoryOutboxStore,
    Message,
    MqConfig,
    OutboxCleaner,
    OutboxPublisher,
    OutboxRecord,
    OutboxStatus,
)


# ------------------------------------------------------------------
# 消息幂等消费（规范 §9.2）
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consumer_first_and_duplicate():
    """首次消费执行业务，同 bizId+msgId 重复消费跳过"""
    store = InMemoryMessageIdempotencyStore()
    consumer = IdempotentConsumer(store)
    processed: list[str] = []

    async def handler(message: Message) -> None:
        processed.append(message.message_id)

    message = Message(topic="order", body={"biz_id": "order-1"})
    assert await consumer.consume(message, handler) is True
    assert await consumer.consume(message, handler) is False  # 重复消费跳过
    assert processed == [message.message_id]


@pytest.mark.asyncio
async def test_consumer_same_biz_different_msg_deduplicated():
    """同一 bizId 不同 msgId（投递重试）也去重（规范 §9.2 覆盖投递重试场景）"""
    store = InMemoryMessageIdempotencyStore()
    consumer = IdempotentConsumer(store)
    processed: list[str] = []

    async def handler(message: Message) -> None:
        processed.append(message.message_id)

    m1 = Message(topic="order", body={"biz_id": "order-9"})
    m2 = Message(topic="order", body={"biz_id": "order-9"})
    assert await consumer.consume(m1, handler) is True
    assert await consumer.consume(m2, handler) is False
    assert len(processed) == 1


@pytest.mark.asyncio
async def test_consumer_failure_rolls_back_key():
    """业务失败回滚幂等键：允许重试（规范 §9.6）"""
    store = InMemoryMessageIdempotencyStore()
    consumer = IdempotentConsumer(store)
    processed: list[str] = []

    async def handler(message: Message) -> None:
        processed.append(message.message_id)
        if len(processed) == 1:
            raise RuntimeError("boom")

    message = Message(topic="order", body={"biz_id": "order-3"})
    with pytest.raises(RuntimeError):
        await consumer.consume(message, handler)
    assert await consumer.consume(message, handler) is True  # 回滚后重试成功
    assert len(processed) == 2


# ------------------------------------------------------------------
# Outbox 本地事务表（规范 §21.3）
# ------------------------------------------------------------------


class _FakePublisher:
    """可控假发布器：按配置注入失败（死信主题投递不失败，用于验证 DLQ 生产链路）"""

    def __init__(self) -> None:
        self.published: list[Message] = []
        self.fail_publish = False
        self.dlq_topic = "web-dlq-topic"

    async def publish(self, message: Message) -> str:
        if self.fail_publish and message.topic != self.dlq_topic:
            raise RuntimeError("broker down")
        self.published.append(message)
        return message.message_id


@pytest.mark.asyncio
async def test_outbox_append_and_publish():
    """追加 -> 轮询投递 -> 状态置为已发送"""
    store = InMemoryOutboxStore()
    publisher = _FakePublisher()
    outbox = OutboxPublisher(store, publisher)

    record = await store.append(OutboxRecord(topic="order", biz_id="order-1", payload={"a": 1}))
    assert record.msg_id
    assert record.status == OutboxStatus.PENDING

    assert await outbox.publish_pending() == 1
    assert publisher.published[0].topic == "order"
    assert publisher.published[0].body == {"a": 1}
    assert await store.next_pending(10) == []  # 已全部投递


@pytest.mark.asyncio
async def test_outbox_publish_failure_retries_then_dlq():
    """投递失败指数退避重试，超限投递死信主题并置死信状态（规范 §9.6/S9-4/P0-3）"""
    store = InMemoryOutboxStore()
    publisher = _FakePublisher()
    publisher.fail_publish = True
    outbox = OutboxPublisher(store, publisher, max_retries=2, config=MqConfig(retry_backoff_seconds=30))

    await store.append(OutboxRecord(topic="order", biz_id="order-2", payload={}))
    assert await outbox.publish_pending() == 0  # 第一次失败 retry_count=1，进入指数退避
    # 退避期未到：next_pending 不再立即返回该记录（S9-4）
    assert await store.next_pending(10) == []
    assert publisher.published == []  # 死信尚未投递
    # 拨快退避到期时间
    async with store._lock:
        for record in store._records.values():
            record.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await outbox.publish_pending() == 0  # 第二次失败 retry_count=2 >= 2 -> 超限

    pending = await store.next_pending(10)
    assert pending == []
    failed = [r for r in store._records.values() if r.status == OutboxStatus.DLQ]
    assert len(failed) == 1  # 超限后状态为死信（P0-3/S9-7）
    assert failed[0].retry_count == 2
    assert publisher.published[-1].topic == "web-dlq-topic"  # 死信消息已投递到死信主题
    assert publisher.published[-1].body["original_topic"] == "order"


@pytest.mark.asyncio
async def test_outbox_cleanup_sent_older_than_retain():
    """已发送超过保留期清理（规范 §21.3）"""
    store = InMemoryOutboxStore()
    publisher = _FakePublisher()
    outbox = OutboxPublisher(store, publisher)
    cleaner = OutboxCleaner(store, retain_days=7)

    record = await store.append(OutboxRecord(topic="order", biz_id="order-4", payload={}))
    await outbox.publish_pending()

    # 模拟记录创建于 8 天前（已超过保留期）
    async with store._lock:
        old = datetime.now(timezone.utc) - timedelta(days=8)
        store._records[record.msg_id].created_at = old

    assert await cleaner.cleanup() == 1
    assert record.msg_id not in store._records


@pytest.mark.asyncio
async def test_outbox_cleanup_keeps_recent():
    """保留期内的已发送记录不清理"""
    store = InMemoryOutboxStore()
    publisher = _FakePublisher()
    outbox = OutboxPublisher(store, publisher)
    cleaner = OutboxCleaner(store, retain_days=7)

    await store.append(OutboxRecord(topic="order", biz_id="order-5", payload={}))
    await outbox.publish_pending()
    assert await cleaner.cleanup() == 0
