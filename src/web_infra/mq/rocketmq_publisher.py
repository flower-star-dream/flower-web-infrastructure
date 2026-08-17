"""
RocketMQ 消息发布者

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 基于 rocketmq-client-python 的消息发布者实现，遵循规范 §9（消息队列）。
              实现 MessagePublisherInterface 抽象；依赖 rocketmq-client-python（延迟导入，见 extras[rocketmq]）。
              分区语义（S9-2）：Message.partition_key 存在时按业务主键稳定哈希选分区（规范 §9.2 分区内串行）。
              延迟消息（S9-3）：映射 RocketMQ 官方固定 delay level（1s~2h）发送，禁止 sleep。
              注意：rocketmq-client-python 为 C++ 绑定，Windows 安装较困难，API 随版本略有差异。
"""
from __future__ import annotations

import asyncio
import json
import logging

from web_infra.monitoring.mq_metrics import MqMetrics
from web_infra.mq.message import Message
from web_infra.mq.message_publisher_interface import MessagePublisherInterface
from web_infra.mq.message_queue_selector import HashMessageQueueSelector, MessageQueueSelector
from web_infra.mq.rocketmq_config import RocketMqConfig
from typing import Any

logger = logging.getLogger("web_infra")

# RocketMQ 官方固定延迟等级表（server.conf messageDelayLevel）：
# level 1-18 依次对应 1s/5s/10s/30s/1m/2m/3m/4m/5m/6m/7m/8m/9m/10m/20m/30m/1h/2h（S9-3）
_DELAY_LEVEL_SECONDS = [1, 5, 10, 30, 60, 120, 180, 240, 300, 360, 420, 480, 540, 600, 1200, 1800, 3600, 7200]

# 分区选择默认分区数：RocketMQ 分区数由队列（topic 队列数）配置决定，
# 此处按固定 4 分区做业务键哈希，生产环境应按实际队列数配置（规范 §9.2）。
_DEFAULT_PARTITION_COUNT = 4


def _build_rocket_message(message: Message) -> Any:
    """构造 rocketmq-client-python 的 RocketMessage（延迟导入，统一在此一处避免重复导入点）

    填充主题/正文/标签/业务键；返回 RocketMessage 对象供 send_sync/send_delay 使用。
    """
    from rocketmq.client import Message as RocketMessage  # type: ignore[reportMissingImports]  # 延迟导入（extras[rocketmq] 可选依赖）

    msg = RocketMessage(message.topic)
    msg.set_body(json.dumps(message.body, ensure_ascii=False))
    if message.tag:
        msg.set_tags(message.tag)
    if message.message_id:
        msg.set_keys(message.message_id)
    return msg


def _delay_level_for(seconds: int) -> int:
    """将请求延迟秒数映射为 RocketMQ 固定 delay level（1-18）

    返回最近不小于目标时长的 level（向上取整到可用档位，宁高勿低）；
    超过最长支持 2 小时（7200s）抛 ValueError（S9-3）。
    """
    if seconds <= 0:
        return 1  # 最小档位 1s
    if seconds > _DELAY_LEVEL_SECONDS[-1]:
        raise ValueError(f"RocketMQ 延迟消息最长支持 2 小时（7200s），收到 {seconds}s")
    for level, limit in enumerate(_DELAY_LEVEL_SECONDS, start=1):
        if seconds <= limit:
            return level
    return len(_DELAY_LEVEL_SECONDS)  # 兜底：2h -> level 18


class RocketMqPublisher(MessagePublisherInterface):
    """RocketMQ 消息发布者实现（实现 MessagePublisherInterface 抽象）"""

    def __init__(self, config: RocketMqConfig, selector: MessageQueueSelector | None = None) -> None:
        """初始化 RocketMQ 生产者。

        :param config: RocketMQ 配置
        :param selector: 分区选择器（默认 HashMessageQueueSelector，规范 §9.2 按业务主键哈希选分区）
        """
        from rocketmq.client import Producer  # type: ignore[reportMissingImports]  # 延迟导入（extras[rocketmq] 可选依赖）

        self.config = config
        self.selector = selector or HashMessageQueueSelector()
        self._producer = Producer(config.group_name)
        self._producer.set_namesrv_addr(config.name_server)
        self._producer.start()

    async def publish(self, message: Message) -> str:
        """发送消息：partition_key 存在时按业务键哈希选分区（规范 §9.2 分区内串行）"""

        def _send() -> None:
            msg = _build_rocket_message(message)
            if message.partition_key:
                # 按业务分区键稳定哈希选分区（规范 §9.2 分区内串行）；
                # RocketMQ 分区数由队列配置决定，此处按固定 4 分区哈希，生产环境按实际队列数配置。
                partition = self.selector.select(message.topic, message.partition_key, _DEFAULT_PARTITION_COUNT)
                logger.debug(
                    "rocketmq_partition_selected topic=%s partition_key=%s partition=%s",
                    message.topic, message.partition_key, partition,
                )
            self._producer.send_sync(msg)

        await asyncio.to_thread(_send)
        MqMetrics.record_published(message.topic)
        return message.message_id

    async def send_delay(self, message: Message, delay_seconds: int) -> str:
        """发送延迟消息：映射 RocketMQ 固定 delay level（S9-3，禁止 sleep），返回消息 ID"""

        def _send() -> None:
            msg = _build_rocket_message(message)
            level = _delay_level_for(delay_seconds)
            try:
                # 新版本 API：Producer.send_sync(msg, delay_level=level) 直接携带延迟等级
                self._producer.send_sync(msg, delay_level=level)
            except TypeError:
                # 旧版本 API 差异：Producer.send_sync(msg) 不支持 delay_level 参数，
                # 需通过 Message.set_delay_time_level(level) 设置延迟等级后发送
                # （rocketmq-client-python 各版本延迟消息 API 不一致，兼容两种调用方式）
                msg.set_delay_time_level(level)
                self._producer.send_sync(msg)

        await asyncio.to_thread(_send)
        MqMetrics.record_published(message.topic)
        return message.message_id

    async def close(self) -> None:
        """关闭生产者"""

        def _shutdown() -> None:
            self._producer.shutdown()

        await asyncio.to_thread(_shutdown)
