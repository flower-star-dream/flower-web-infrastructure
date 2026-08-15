"""
MQ 分区与延迟消息整改单元测试（规范 §9.2/S9-2/S9-3/S9-5）

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证分区与延迟消息整改：
              - HashMessageQueueSelector 稳定哈希分区（相同 key 同分区、不同 key 分布、None 归 0）
              - InMemoryMessageQueue 带 partition_key 发布/订阅正常消费，分区内串行
              - send_delay 到期后消费 / cancel_delayed 取消后不消费（到期二次校验）
              - RocketMqPublisher._delay_level_for 延迟等级映射（模块级函数直接测试，不实例化 producer）
"""
import asyncio

import pytest

from web_infra.mq import InMemoryMessageQueue, Message
from web_infra.mq.message_queue_selector import HashMessageQueueSelector
from web_infra.mq.rocketmq_publisher import _delay_level_for


def _collect(target: list[Message]):
    """构造收集消息的异步订阅处理器"""
    async def _handle(message: Message) -> None:
        target.append(message)

    return _handle


# ------------------------------------------------------------------
# 整改 1：分区选择器（S9-2/规范 §9.2）
# ------------------------------------------------------------------


def test_hash_selector_same_key_same_partition():
    """相同 partition_key 恒得到相同分区（稳定哈希）"""
    selector = HashMessageQueueSelector()
    assert selector.select("order", "user-1001", 4) == selector.select("order", "user-1001", 4)
    assert selector.select("pay", "biz-42", 8) == selector.select("pay", "biz-42", 8)


def test_hash_selector_none_key_returns_zero():
    """partition_key 为 None 返回 0；partition_count<=0 返回 0"""
    selector = HashMessageQueueSelector()
    assert selector.select("order", None, 4) == 0
    assert selector.select("order", "", 4) == 0
    assert selector.select("order", "user-1", 0) == 0
    assert selector.select("order", "user-1", -1) == 0


def test_hash_selector_distributes_across_partitions():
    """不同 partition_key 分布到多个分区，且落在合法区间内"""
    selector = HashMessageQueueSelector()
    partitions = {selector.select("order", f"user-{i}", 4) for i in range(100)}
    assert len(partitions) > 1  # 多 key 分布到不止一个分区
    assert all(0 <= p < 4 for p in partitions)


# ------------------------------------------------------------------
# 整改 2：内存队列分区消费（S9-2）
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_memory_publish_with_partition_key():
    """带 partition_key 的发布/订阅正常消费，字段透传不变"""
    mq = InMemoryMessageQueue(partition_count=4)
    received: list[Message] = []
    mq.subscribe("order", _collect(received))
    await mq.start()

    message = Message(topic="order", partition_key="user-1", body={"biz_id": "p-1"})
    assert await mq.publish(message) == message.message_id

    await asyncio.sleep(0.05)
    await mq.stop()

    assert len(received) == 1
    assert received[0].partition_key == "user-1"
    assert received[0].body == {"biz_id": "p-1"}


@pytest.mark.asyncio
async def test_in_memory_same_partition_serial_consume():
    """同一业务分区键的消息按发布顺序串行消费（分区内串行，规范 §9.2）"""
    mq = InMemoryMessageQueue()
    received: list[Message] = []
    mq.subscribe("order", _collect(received))
    await mq.start()

    for i in range(5):
        await mq.publish(Message(topic="order", partition_key="user-same", body={"seq": i}))

    await asyncio.sleep(0.1)
    await mq.stop()

    assert [m.body["seq"] for m in received] == [0, 1, 2, 3, 4]  # 分区内按序消费


# ------------------------------------------------------------------
# 整改 3：延迟消息到期二次校验（S9-3/规范 §9.5）
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_delay_delivers_after_expiry():
    """send_delay 到期后正常投递并被消费"""
    mq = InMemoryMessageQueue()
    received: list[Message] = []
    mq.subscribe("order", _collect(received))
    await mq.start()

    message = Message(topic="order", partition_key="user-2", body={"biz_id": "d-1"})
    assert await mq.send_delay(message, 0.05) == message.message_id

    # 轮询等待投递（最多 2s），避免固定 sleep 在高负载下的时序抖动（flaky 治理）
    deadline = asyncio.get_event_loop().time() + 2.0
    while not received and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.02)
    await mq.stop()

    assert len(received) == 1
    assert received[0].message_id == message.message_id
    assert received[0].partition_key == "user-2"


@pytest.mark.asyncio
async def test_send_delay_cancelled_not_delivered():
    """cancel_delayed 取消后到期不投递（延迟到期二次校验，S9-3）"""
    mq = InMemoryMessageQueue()
    received: list[Message] = []
    mq.subscribe("order", _collect(received))
    await mq.start()

    message = Message(topic="order", body={"biz_id": "d-2"})
    await mq.send_delay(message, 0.05)
    assert mq.cancel_delayed(message.message_id) is True  # 延迟期内可取消

    await asyncio.sleep(0.5)  # 等待超过延迟期，确认已取消的延迟消息不被投递
    await mq.stop()

    assert len(received) == 0  # 已取消的延迟消息到期被二次校验丢弃
    assert mq.cancel_delayed("no-such-id") is False  # 不存在的延迟消息取消失败


# ------------------------------------------------------------------
# 整改 4：RocketMQ 延迟等级映射（S9-3，模块级函数直接测试）
# ------------------------------------------------------------------


def test_delay_level_for_mapping():
    """请求秒数映射为最近不小于目标的 RocketMQ delay level（1-18）"""
    assert _delay_level_for(1) == 1   # 1s
    assert _delay_level_for(3) == 2   # 5s
    assert _delay_level_for(5) == 2   # 5s
    assert _delay_level_for(8) == 3   # 10s
    assert _delay_level_for(30) == 4  # 30s
    assert _delay_level_for(60) == 5  # 1m
    assert _delay_level_for(600) == 14  # 10m
    assert _delay_level_for(1200) == 15  # 20m
    assert _delay_level_for(1800) == 16  # 30m
    assert _delay_level_for(3600) == 17  # 1h
    assert _delay_level_for(7200) == 18  # 2h（最大档位）
    assert _delay_level_for(0) == 1  # 非正数钳制到最小档位 1s


def test_delay_level_for_exceeds_max_raises():
    """超过 2 小时抛 ValueError（S9-3）"""
    with pytest.raises(ValueError):
        _delay_level_for(7201)
