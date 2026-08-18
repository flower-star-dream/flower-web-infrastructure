"""
MQ 韧性整改单元测试（退避 / DLQ / 消费异常分类 / MySQL Outbox 存储）

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证韧性整改（规范 §9.6/S9-4/P0-3/S9-7/S9-1/S21-1）：
              - Outbox 投递指数退避（失败后 next_pending 不立即返回）
              - 重试超限进 DLQ（死信消息可被订阅者消费）
              - DlqConsumer 订阅死信主题与重投递回 Outbox 钩子
              - RetryableConsumer 可重试/不可重试异常分流（超限或不可重试进 DLQ）
              - InMemoryMessageQueue 消费失败重试/死信（不再静默丢弃）
              - MysqlOutboxStore CRUD 与退避语义（sqlite+aiosqlite 内存库验证）
              - register_outbox_tasks 定时任务装配（S21-2）
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from web_infra.capabilities.mq import (
    DlqConsumer,
    InMemoryMessageQueue,
    InMemoryOutboxStore,
    Message,
    MqConfig,
    MysqlOutboxStore,
    NonRetryableError,
    OutboxPublisher,
    OutboxRecord,
    OutboxStatus,
    RetryableConsumer,
    RetryableError,
    requeue_dlq_to_outbox,
    register_outbox_tasks,
)
from web_infra.capabilities.schedule import TaskScheduler


# ------------------------------------------------------------------
# 整改 1/2：Outbox 指数退避 + 重试超限进 DLQ（S9-4/P0-3）
# ------------------------------------------------------------------


class _FailThenOkPublisher:
    """假发布器：业务主题投递失败 fail_times 次后成功，死信主题投递恒成功；
    成功投递时可选转发给内存消息队列（验证死信消息可被订阅者消费）"""

    def __init__(self, fail_times: int = 0, mq: InMemoryMessageQueue | None = None) -> None:
        self.fail_times = fail_times
        self.mq = mq
        self.attempts: dict[str, int] = {}
        self.published: list[Message] = []

    async def publish(self, message: Message) -> str:
        if message.topic != "web-dlq-topic":
            self.attempts[message.message_id] = self.attempts.get(message.message_id, 0) + 1
            if self.attempts[message.message_id] <= self.fail_times:
                raise RuntimeError("broker down")
        self.published.append(message)
        if self.mq is not None:
            await self.mq.publish(message)
        return message.message_id


def _collect(target: list[Message]):
    """构造收集消息的异步订阅处理器"""
    async def _handle(message: Message) -> None:
        target.append(message)

    return _handle


@pytest.mark.asyncio
async def test_outbox_backoff_prevents_immediate_retry():
    """投递失败后进入退避期：next_pending 不立即返回该记录（S9-4）"""
    store = InMemoryOutboxStore()
    publisher = _FailThenOkPublisher(fail_times=99)
    outbox = OutboxPublisher(store, publisher, config=MqConfig(max_retry=3, retry_backoff_seconds=60))

    await store.append(OutboxRecord(topic="order", biz_id="o-1", payload={"a": 1}))
    assert await outbox.publish_pending() == 0  # 首次失败

    # 退避未到期：立即重试取不到（失败记录仍 PENDING 但 next_retry_at 在未来）
    assert await store.next_pending(10) == []
    record = next(iter(store._records.values()))
    assert record.status == OutboxStatus.PENDING
    assert record.retry_count == 1
    assert record.next_retry_at is not None and record.next_retry_at > datetime.now(timezone.utc)

    # 退避到期后可再次投递
    async with store._lock:
        record.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await outbox.publish_pending() == 0  # 第二次失败
    assert next(iter(store._records.values())).retry_count == 2


@pytest.mark.asyncio
async def test_outbox_over_retry_goes_to_dlq_and_consumable():
    """重试超限：投递死信主题、状态置死信，死信消息可被订阅者消费（P0-3/S9-7）"""
    mq = InMemoryMessageQueue(dead_letter_topic="web-dlq-topic")
    dlq_received: list[Message] = []
    mq.subscribe("web-dlq-topic", _collect(dlq_received))
    await mq.start()

    store = InMemoryOutboxStore()
    publisher = _FailThenOkPublisher(fail_times=99, mq=mq)  # 业务投递恒失败，死信投递成功并进入 mq 队列
    outbox = OutboxPublisher(store, publisher, config=MqConfig(max_retry=2, retry_backoff_seconds=1))

    record = await store.append(OutboxRecord(topic="order", biz_id="o-2", payload={"k": "v"}))
    assert await outbox.publish_pending() == 0  # 第 1 次失败，退避 1s
    # 退避到期
    async with store._lock:
        store._records[record.msg_id].next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await outbox.publish_pending() == 0  # 第 2 次失败 -> 超限进 DLQ

    # Outbox 状态为死信
    assert store._records[record.msg_id].status == OutboxStatus.DLQ
    assert store._records[record.msg_id].dlq_at is not None
    assert store._records[record.msg_id].retry_count == 2
    # 死信消息投递到死信主题并可被订阅者收到
    await asyncio.sleep(0.05)
    await mq.stop()
    assert len(dlq_received) == 1
    assert dlq_received[0].topic == "web-dlq-topic"
    assert dlq_received[0].body["original_msg_id"] == record.msg_id
    assert dlq_received[0].body["original_topic"] == "order"
    assert dlq_received[0].body["payload"] == {"k": "v"}


# ------------------------------------------------------------------
# 整改 2：DLQ 消费者（订阅死信主题 + 重投递回 Outbox 钩子）
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dlq_consumer_receives_and_requeue():
    """DlqConsumer 订阅死信主题收到消息，requeue_dlq_to_outbox 重投递回 Outbox（P0-3）"""
    mq = InMemoryMessageQueue()
    handled: list[Message] = []
    consumer = DlqConsumer(mq, dlq_topic="web-dlq-topic", on_dlq=_collect(handled))
    await consumer.start()
    dlq_message = Message(
        topic="web-dlq-topic",
        body={"original_msg_id": "m-1", "original_topic": "order", "biz_id": "b-1", "payload": {"a": 1}},
    )
    await mq.publish(dlq_message)
    await asyncio.sleep(0.05)
    await consumer.stop()

    assert len(handled) == 1
    assert handled[0].body["original_topic"] == "order"

    # 重投递回 Outbox：新记录恢复待发送，topic 回落到业务主题
    store = InMemoryOutboxStore()
    record = await requeue_dlq_to_outbox(store, handled[0])
    assert record.topic == "order"
    assert record.payload == {"a": 1}
    assert record.status == OutboxStatus.PENDING
    assert (await store.next_pending(10))[0].msg_id == record.msg_id


# ------------------------------------------------------------------
# 整改 3：消费异常分类与重试/DLQ 入口（S9-1）
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retryable_consumer_non_retryable_goes_to_dlq():
    """不可重试异常（NonRetryableError）立即进 DLQ，不重试（S9-1）"""
    mq = InMemoryMessageQueue(dead_letter_topic="web-dlq-topic")
    dlq_received: list[Message] = []
    mq.subscribe("web-dlq-topic", _collect(dlq_received))
    await mq.start()

    consumer = RetryableConsumer(mq, max_retries=3, retry_backoff_seconds=0.01)
    calls = 0

    async def bad_handler(message: Message) -> None:
        nonlocal calls
        calls += 1
        raise NonRetryableError("invalid payload")

    message = Message(topic="order", body={"biz_id": "b-1"})
    assert await consumer.consume(message, bad_handler) is False  # 已进 DLQ
    assert calls == 1  # 不可重试不重试
    await asyncio.sleep(0.05)
    await mq.stop()
    assert len(dlq_received) == 1
    assert dlq_received[0].body["original_topic"] == "order"


@pytest.mark.asyncio
async def test_retryable_consumer_retries_then_success():
    """可重试异常指数退避重试，重试后成功返回 True（S9-1）"""
    mq = InMemoryMessageQueue()
    consumer = RetryableConsumer(mq, max_retries=3, retry_backoff_seconds=0.01)
    attempts = 0

    async def flaky_handler(message: Message) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RetryableError("net timeout")

    message = Message(topic="order", body={"biz_id": "b-2"})
    assert await consumer.consume(message, flaky_handler) is True
    assert attempts == 3


@pytest.mark.asyncio
async def test_retryable_consumer_over_retry_goes_to_dlq():
    """可重试异常超过上限进 DLQ，返回 False（S9-1/P0-3）"""
    mq = InMemoryMessageQueue(dead_letter_topic="web-dlq-topic")
    dlq_received: list[Message] = []
    mq.subscribe("web-dlq-topic", _collect(dlq_received))
    await mq.start()

    consumer = RetryableConsumer(mq, max_retries=2, retry_backoff_seconds=0.01)
    attempts = 0

    async def always_fail(message: Message) -> None:
        nonlocal attempts
        attempts += 1
        raise RetryableError("boom")

    message = Message(topic="order", body={"biz_id": "b-3"})
    assert await consumer.consume(message, always_fail) is False
    assert attempts == 2  # 重试 2 次后超限
    await asyncio.sleep(0.05)
    await mq.stop()
    assert len(dlq_received) == 1
    assert dlq_received[0].body["retry_count"] == 2


@pytest.mark.asyncio
async def test_in_memory_queue_retries_then_consumes():
    """内存队列消费失败（可重试）指数退避重新入队，重试成功后不丢消息（S9-1）"""
    mq = InMemoryMessageQueue(max_retries=2, retry_backoff_seconds=0.01, dead_letter_topic="web-dlq-topic")
    attempts = 0

    async def flaky_handler(message: Message) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RetryableError("net timeout")

    mq.subscribe("order", flaky_handler)
    await mq.start()
    await mq.publish(Message(topic="order", body={"biz_id": "b-4"}))
    await asyncio.sleep(0.3)
    await mq.stop()

    assert attempts == 3  # 前两次失败重试，第三次成功


@pytest.mark.asyncio
async def test_in_memory_queue_non_retryable_goes_to_dlq():
    """内存队列消费不可重试异常直接进 DLQ，不再静默丢弃（S9-1）"""
    mq = InMemoryMessageQueue(max_retries=3, retry_backoff_seconds=0.01, dead_letter_topic="web-dlq-topic")
    dlq_received: list[Message] = []
    mq.subscribe("web-dlq-topic", _collect(dlq_received))

    async def bad_handler(message: Message) -> None:
        raise NonRetryableError("validation failed")

    mq.subscribe("order", bad_handler)
    await mq.start()
    await mq.publish(Message(topic="order", body={"biz_id": "b-5"}))
    await asyncio.sleep(0.1)
    await mq.stop()

    assert len(dlq_received) == 1
    assert dlq_received[0].body["original_topic"] == "order"


@pytest.mark.asyncio
async def test_in_memory_queue_over_retry_goes_to_dlq():
    """内存队列可重试异常超过上限进 DLQ（S9-1/P0-3）"""
    mq = InMemoryMessageQueue(max_retries=2, retry_backoff_seconds=0.01, dead_letter_topic="web-dlq-topic")
    dlq_received: list[Message] = []
    mq.subscribe("web-dlq-topic", _collect(dlq_received))

    async def always_fail(message: Message) -> None:
        raise RetryableError("boom")

    mq.subscribe("order", always_fail)
    await mq.start()
    await mq.publish(Message(topic="order", body={"biz_id": "b-6"}))
    await asyncio.sleep(0.3)
    await mq.stop()

    assert len(dlq_received) == 1
    assert dlq_received[0].body["original_msg_id"]  # 死信消息包裹原始消息
    assert dlq_received[0].body["original_topic"] == "order"


# ------------------------------------------------------------------
# 整改 4：MySQL Outbox 存储（sqlite 内存库验证 SQL 语义，S21-1）
# ------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE message_outbox (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id        VARCHAR(64) NOT NULL,
    biz_id        VARCHAR(64) NOT NULL,
    topic         VARCHAR(128) NOT NULL,
    tag           VARCHAR(64),
    payload       TEXT NOT NULL,
    status        TINYINT NOT NULL DEFAULT 0,
    retry_count   INT NOT NULL DEFAULT 0,
    created_at    DATETIME NOT NULL,
    updated_at    DATETIME,
    cleaned_at    DATETIME,
    next_retry_at DATETIME,
    UNIQUE (msg_id, biz_id)
)
"""


@pytest_asyncio.fixture
async def mysql_store():
    """sqlite+aiosqlite 内存库构造 MysqlOutboxStore（验证 SQL 语义）"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text(_CREATE_TABLE_SQL))
        await session.commit()
    store = MysqlOutboxStore(factory)
    yield store
    await engine.dispose()


@pytest.mark.asyncio
async def test_mysql_outbox_store_append_and_pending(mysql_store):
    """MysqlOutboxStore：追加 -> 待发送查询（CRUD 语义）"""
    record = await mysql_store.append(OutboxRecord(topic="order", biz_id="o-1", payload={"a": 1}))
    assert record.msg_id
    assert record.status == OutboxStatus.PENDING

    pending = await mysql_store.next_pending(10)
    assert len(pending) == 1
    assert pending[0].topic == "order"
    assert pending[0].payload == {"a": 1}
    assert pending[0].msg_id == record.msg_id

    await mysql_store.mark_sent(record.msg_id)
    assert await mysql_store.next_pending(10) == []  # 已发送不再返回


@pytest.mark.asyncio
async def test_mysql_outbox_store_backoff_semantics(mysql_store):
    """MysqlOutboxStore：mark_failed 设置退避时间，next_pending 仅取到期记录；超限置失败（S9-4）"""
    record = await mysql_store.append(OutboxRecord(topic="order", biz_id="o-2", payload={}))
    await mysql_store.mark_failed(record.msg_id, max_retries=3, retry_delay_seconds=60)
    # 退避期内不返回
    assert await mysql_store.next_pending(10) == []

    # 拨快退避到期时间后再次取到，且 retry_count 递增
    async with mysql_store._session_scope() as session:
        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        await session.execute(
            text("UPDATE message_outbox SET next_retry_at = :past WHERE msg_id = :m"),
            {"past": past, "m": record.msg_id},
        )
    pending = await mysql_store.next_pending(10)
    assert len(pending) == 1
    assert pending[0].retry_count == 1
    assert pending[0].next_retry_at is not None

    # 超限：状态置失败并清除退避时间
    await mysql_store.mark_failed(record.msg_id, max_retries=3, retry_delay_seconds=60)  # retry=2
    await mysql_store.mark_failed(record.msg_id, max_retries=3, retry_delay_seconds=60)  # retry=3 >= 3
    assert await mysql_store.next_pending(10) == []
    async with mysql_store._session_scope() as session:
        row = (await session.execute(
            text("SELECT status, retry_count, next_retry_at FROM message_outbox WHERE msg_id = :m"),
            {"m": record.msg_id},
        )).mappings().first()
    assert int(row["status"]) == int(OutboxStatus.FAILED)
    assert int(row["retry_count"]) == 3
    assert row["next_retry_at"] is None


@pytest.mark.asyncio
async def test_mysql_outbox_store_append_in_business_transaction(mysql_store):
    """MysqlOutboxStore.append 接受业务会话同事务写入：业务回滚则 Outbox 消息一并回滚（S21-1）"""
    async with mysql_store._session_scope() as session:
        await mysql_store.append(OutboxRecord(topic="order", biz_id="o-3", payload={}), session=session)
        await session.rollback()  # 业务事务回滚
    assert await mysql_store.next_pending(10) == []  # 未提交的消息不可见

    # 同事务提交后可见
    async with mysql_store._session_scope() as session:
        await session.execute(
            text("INSERT INTO message_outbox (msg_id, biz_id, topic, payload, status, retry_count, created_at) "
                 "VALUES (:m, :b, :t, :p, 0, 0, :now)"),
            {"m": "tx-1", "b": "o-3", "t": "order", "p": "{}",
             "now": datetime.now(timezone.utc).replace(tzinfo=None)},
        )
        await session.commit()
    assert len(await mysql_store.next_pending(10)) == 1


@pytest.mark.asyncio
async def test_mysql_outbox_store_cleanup_sent(mysql_store):
    """MysqlOutboxStore：清理已发送超过保留期的记录（规范 §21.3）"""
    record = await mysql_store.append(OutboxRecord(topic="order", biz_id="o-4", payload={}))
    await mysql_store.mark_sent(record.msg_id)
    # 拨旧 created_at 到 8 天前（超过默认保留期）
    async with mysql_store._session_scope() as session:
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=8)
        await session.execute(
            text("UPDATE message_outbox SET created_at = :old WHERE msg_id = :m"),
            {"old": old, "m": record.msg_id},
        )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert await mysql_store.cleanup_sent(now) == 1
    assert await mysql_store.next_pending(10) == []


# ------------------------------------------------------------------
# 整改 5：Outbox 定时任务装配（S21-2）
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_outbox_tasks_registers_publish_and_cleanup():
    """register_outbox_tasks 注册轮询投递与清理定时任务（S21-2）"""
    scheduler = TaskScheduler()
    store = InMemoryOutboxStore()
    publisher = _FailThenOkPublisher()
    names = register_outbox_tasks(
        scheduler, store, publisher,
        config=MqConfig(max_retry=2, retry_backoff_seconds=1),
        publish_interval_seconds=1,
        cleanup_interval_seconds=60,
    )
    assert names == ["message-outbox-publish", "message-outbox-cleanup"]

    await store.append(OutboxRecord(topic="order", biz_id="o-5", payload={}))
    await scheduler.run_once("message-outbox-publish")
    assert len(publisher.published) == 1  # 轮询投递任务实际执行

    await scheduler.run_once("message-outbox-cleanup")  # 清理任务可执行不抛错
    assert not scheduler.is_paused("message-outbox-publish")
