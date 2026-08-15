"""
消息队列组件指标采集器

@Author: 花海
@Date: 2026/08/14 23:30
@Description: 消息队列组件（memory/rocketmq）指标采集，懒注册模式：
              指标仅在组件实际被调用（启用）时注册，未启用组件不展现任何指标，
              由组件启用配置（app.mq.type）动态决定是否采集。
              队列积压（pending）为 Gauge，由组件 update_metrics 在 /metrics 抓取时刷新。
"""
from __future__ import annotations

from threading import Lock
from typing import ClassVar

from prometheus_client import Counter, Gauge

from web_infra.monitoring.component_metrics_interface import ComponentMetricsCollector


class MqMetrics(ComponentMetricsCollector):
    """消息队列组件指标采集器（懒注册：首次记录时注册指标）"""

    _registered: ClassVar[bool] = False
    # S16-2 豁免：临界区为纯内存操作，无 I/O 阻塞，不适用 3s 获取超时
    _lock: ClassVar[Lock] = Lock()

    published_total: ClassVar[Counter | None] = None
    consumed_total: ClassVar[Counter | None] = None
    errors_total: ClassVar[Counter | None] = None
    dlq_total: ClassVar[Counter | None] = None
    pending: ClassVar[Gauge | None] = None

    @classmethod
    def ensure(cls) -> None:
        """注册消息队列指标（线程安全，仅首次执行）"""
        if cls._registered:
            return
        with cls._lock:
            if cls._registered:
                return
            cls.published_total = Counter("mq_published_total", "MQ 发布消息数", ["topic"])
            cls.consumed_total = Counter("mq_consumed_total", "MQ 消费消息数", ["topic"])
            cls.errors_total = Counter("mq_errors_total", "MQ 处理错误数", ["topic", "phase"])
            cls.dlq_total = Counter("mq_dlq_messages_total", "MQ 死信消息数（低基数，label=topic）", ["topic"])
            cls.pending = Gauge("mq_pending", "MQ 队列积压消息数", ["topic"])
            cls._registered = True

    @classmethod
    def record_published(cls, topic: str) -> None:
        """记录一条消息发布成功"""
        cls.ensure()
        counter = cls.published_total
        assert counter is not None  # ensure() 已注册
        counter.labels(topic).inc()

    @classmethod
    def record_consumed(cls, topic: str) -> None:
        """记录一条消息消费成功"""
        cls.ensure()
        counter = cls.consumed_total
        assert counter is not None
        counter.labels(topic).inc()

    @classmethod
    def record_error(cls, topic: str, phase: str) -> None:
        """记录一次处理错误（phase: publish/consume）"""
        cls.ensure()
        counter = cls.errors_total
        assert counter is not None
        counter.labels(topic, phase).inc()

    @classmethod
    def record_dlq(cls, topic: str) -> None:
        """记录一条消息进入死信队列（P0-3/S9-7 死信监控，label=topic 低基数）"""
        cls.ensure()
        counter = cls.dlq_total
        assert counter is not None
        counter.labels(topic).inc()

    @classmethod
    def update_pending(cls, topic: str, count: int) -> None:
        """刷新指定主题的队列积压数（组件 update_metrics 调用）"""
        cls.ensure()
        pending = cls.pending
        assert pending is not None
        pending.labels(topic).set(max(count, 0))
