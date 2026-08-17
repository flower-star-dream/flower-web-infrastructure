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

from threading import Lock
from typing import Callable, ClassVar

from web_infra.config import Settings
from web_infra.mq.message_publisher_interface import MessagePublisherInterface

#: 消息队列工厂签名：入参装配配置（Settings），返回消息发布器实现
MessageQueueFactory = Callable[[Settings], MessagePublisherInterface]


class MessageQueueRegistry:
    """消息队列注册表（类级注册，全局装配；同名覆盖）"""

    _factories: ClassVar[dict[str, MessageQueueFactory]] = {}
    _lock = Lock()

    @classmethod
    def register(cls, name: str, factory: MessageQueueFactory) -> None:
        """注册队列后端工厂（同名覆盖）。

        :param name: type 名（与 yml app.mq.type 匹配）
        :param factory: 工厂，入参 Settings，返回 MessagePublisherInterface 实现
        """
        with cls._lock:
            cls._factories[name] = factory

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销后端（不存在时静默）"""
        with cls._lock:
            cls._factories.pop(name, None)

    @classmethod
    def get(cls, name: str) -> MessageQueueFactory:
        """按名查询工厂；未注册抛 KeyError（装配期由 create_app 捕获转 ConfigError）"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory

    @classmethod
    def create(cls, name: str, settings: Settings) -> MessagePublisherInterface:
        """按名实例化队列后端；未注册抛 KeyError"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory(settings)

    @classmethod
    def registered_names(cls) -> list[str]:
        """已注册后端名清单"""
        with cls._lock:
            return list(cls._factories)


def _memory_mq_factory(settings: Settings) -> MessagePublisherInterface:
    """内置 memory：进程内消息队列（单机/测试场景）"""
    from web_infra.mq.in_memory_message_queue import InMemoryMessageQueue

    return InMemoryMessageQueue()


def _rocketmq_factory(settings: Settings) -> MessagePublisherInterface:
    """内置 rocketmq：RocketMQ 消息发布器（多实例/微服务场景）"""
    from web_infra.mq.rocketmq_config import RocketMqConfig
    from web_infra.mq.rocketmq_publisher import RocketMqPublisher

    config = RocketMqConfig(
        **{
            field: settings.get(f"app.mq.rocketmq.{field}")
            for field in RocketMqConfig.model_fields
            if settings.get(f"app.mq.rocketmq.{field}") is not None
        }
    )
    return RocketMqPublisher(config)


# 内置后端条目（模块导入即注册，幂等）
MessageQueueRegistry.register("memory", _memory_mq_factory)
MessageQueueRegistry.register("rocketmq", _rocketmq_factory)
