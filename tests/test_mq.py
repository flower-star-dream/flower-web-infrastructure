"""
消息队列抽象单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证内存消息队列的发布/订阅/分发行为（规范 §9）。
"""
import asyncio

import pytest

from web_infra.mq import InMemoryMessageQueue, Message


@pytest.mark.asyncio
async def test_publish_and_consume():
    """发布消息并分发到订阅者"""
    mq = InMemoryMessageQueue()
    received: list[Message] = []

    async def handler(message: Message) -> None:
        received.append(message)

    mq.subscribe("web-order-topic", handler)
    await mq.start()

    message = Message(topic="web-order-topic", body={"id": 1})
    message_id = await mq.publish(message)

    await asyncio.sleep(0.05)
    await mq.stop()

    assert message_id == message.message_id
    assert len(received) == 1
    assert received[0].body == {"id": 1}


def test_message_structure():
    """消息结构包含 code 与 message_id（规范 §4.5.4）"""
    message = Message(topic="web-order-topic", body={"id": 1})
    assert message.code == "S0000"
    assert message.message_id  # 自动生成唯一标识
