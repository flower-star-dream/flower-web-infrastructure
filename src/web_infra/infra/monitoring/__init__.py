"""
指标监控模块

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 指标采集（Prometheus）+ 分阶段耗时埋点，遵循规范 §18；
              AI 模型调用指标（TTFT/Token/成本/降级）遵循 AI 规范 §15；
              连接池/Python 运行时/线程池指标采集（§18.5.4）；
              缓存/存储/消息队列/注册中心组件指标采集（懒注册，由组件启用配置动态决定是否采集）；
              /metrics 浏览器 HTML 可视化页面（内容协商、按样本动态渲染分组）与自定义指标分组 SPI。
"""
from web_infra.infra.monitoring.phase_timer import PhaseTimer
from web_infra.infra.monitoring.slow_request_store import SlowRequestStore
from web_infra.infra.monitoring.ai_metrics import (
    init_ai_metrics,
    record_ai_call,
    record_ai_ttft,
    record_ai_duration,
    record_ai_tokens,
    record_ai_cost,
)
from web_infra.infra.monitoring.metrics_html import render_metrics_html, should_render_html
from web_infra.infra.monitoring.pool_metrics import (
    record_mysql_pool_metrics,
    record_redis_pool_metrics,
    record_mongo_pool_metrics,
)
from web_infra.infra.monitoring.runtime_metrics import ThreadPoolMetrics, record_runtime_metrics
from web_infra.infra.monitoring.cache_metrics import CacheMetrics
from web_infra.infra.monitoring.storage_metrics import StorageMetrics
from web_infra.infra.monitoring.mq_metrics import MqMetrics
from web_infra.infra.monitoring.registry_metrics import RegistryMetrics
from web_infra.infra.monitoring.component_metrics_interface import ComponentMetricsCollector
from web_infra.infra.monitoring.metric_group_provider_interface import MetricGroupProviderInterface
from web_infra.infra.monitoring.metric_group_provider_registry import MetricGroupProviderRegistry

__all__ = [
    "PhaseTimer",
    "SlowRequestStore",
    "init_ai_metrics",
    "record_ai_call",
    "record_ai_ttft",
    "record_ai_duration",
    "record_ai_tokens",
    "record_ai_cost",
    "render_metrics_html",
    "should_render_html",
    "record_mysql_pool_metrics",
    "record_redis_pool_metrics",
    "record_mongo_pool_metrics",
    "ThreadPoolMetrics",
    "record_runtime_metrics",
    "CacheMetrics",
    "StorageMetrics",
    "MqMetrics",
    "RegistryMetrics",
    "ComponentMetricsCollector",
    "MetricGroupProviderInterface",
    "MetricGroupProviderRegistry",
]
