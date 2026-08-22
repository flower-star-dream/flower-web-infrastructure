"""
消息队列注册表

@Author: 花海
@Date: 2026/08/17 17:00
@Description: 消息队列 SPI 注册表：按 type 名注册/查询 MessagePublisherInterface 工厂，
              装配期（app.mq.type）按名实例化；内置 memory/rocketmq 条目，
              用户自定义队列后端（Kafka/RabbitMQ 等）经 register 注册后即可接入 create_app，
              无需改动框架装配代码；未注册的 type 装配期快速失败（ConfigError）。
"""
from __future__ import annotations

from typing import Callable

from web_infra.capabilities.mq.message_publisher_interface import MessagePublisherInterface
from web_infra.core.spi import SpiRegistry
from web_infra.infra.config import Settings

#: 消息队列工厂签名：入参装配配置（Settings），返回消息发布器实现
MessageQueueFactory = Callable[[Settings], MessagePublisherInterface]


class MessageQueueRegistry(SpiRegistry):
    """消息队列注册表（SpiRegistry 基类：命名空间隔离 + 内置默认保护；同名覆盖默认拒绝）"""

    @classmethod
    def create(cls, name: str, settings: Settings) -> MessagePublisherInterface:
        """按名实例化队列后端；未注册抛 KeyError"""
        return cls.get(name)(settings)


def _memory_mq_factory(settings: Settings) -> MessagePublisherInterface:
    """内置 memory：进程内消息队列（单机/测试场景）"""
    from web_infra.capabilities.mq.in_memory_message_queue import InMemoryMessageQueue

    return InMemoryMessageQueue()


def _rocketmq_factory(settings: Settings) -> MessagePublisherInterface:
    """内置 rocketmq：RocketMQ 消息发布器（多实例/微服务场景）"""
    from web_infra.capabilities.mq.rocketmq_config import RocketMqConfig
    from web_infra.capabilities.mq.rocketmq_publisher import RocketMqPublisher

    config = RocketMqConfig(
        **{
            field: settings.get(f"app.mq.rocketmq.{field}")
            for field in RocketMqConfig.model_fields
            if settings.get(f"app.mq.rocketmq.{field}") is not None
        }
    )
    return RocketMqPublisher(config)


# 内置后端条目（模块导入即注册，幂等；落框架命名空间，受保护）
MessageQueueRegistry.register("memory", _memory_mq_factory, namespace=MessageQueueRegistry.FRAMEWORK_NAMESPACE)
MessageQueueRegistry.register("rocketmq", _rocketmq_factory, namespace=MessageQueueRegistry.FRAMEWORK_NAMESPACE)
