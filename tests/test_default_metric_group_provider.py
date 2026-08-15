"""
默认指标分组提供者测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证 DefaultMetricGroupProvider（规范 S3-2 默认实现）：
              默认映射分组、自定义映射覆盖、未知前缀归 other，以及注册到 SPI 注册表后生效。
"""
from web_infra.monitoring.default_metric_group_provider import DefaultMetricGroupProvider
from web_infra.monitoring.metric_group_provider_registry import MetricGroupProviderRegistry


def test_default_map_groups_by_prefix():
    """默认映射：web_/db_/mq_/ai_/cache_ 前缀分别归入对应分组"""
    provider = DefaultMetricGroupProvider()
    assert provider.group("web_http_requests_total") == "web"
    assert provider.group("db_query_seconds") == "db"
    assert provider.group("mq_consume_total") == "mq"
    assert provider.group("ai_call_total") == "ai"
    assert provider.group("cache_hit_total") == "cache"


def test_custom_map_overrides_default():
    """自定义映射覆盖默认映射：未覆盖前缀归 other"""
    provider = DefaultMetricGroupProvider(group_map={"biz_": "biz"})
    assert provider.group("biz_order_total") == "biz"
    assert provider.group("web_http_requests_total") == "other"


def test_unknown_prefix_falls_back_to_other():
    """未知前缀归 other"""
    provider = DefaultMetricGroupProvider()
    assert provider.group("storage_object_total") == "other"
    assert provider.group("") == "other"


def test_series_label_zh_returns_none():
    """默认提供者不提供标签中文翻译，返回 None 走默认 k=v 展示"""
    provider = DefaultMetricGroupProvider()
    assert provider.series_label_zh("web_http_requests_total", (("status", "200"),)) is None


def test_registrable_to_spi_registry():
    """可作为 MetricGroupProviderInterface 实现注册到 SPI 注册表（S3-2 默认实现可接入）"""
    provider = DefaultMetricGroupProvider()
    MetricGroupProviderRegistry.register(provider)
    try:
        assert MetricGroupProviderRegistry.provider_of(provider.group_name) is provider
        assert MetricGroupProviderRegistry.group_of("web_http_requests_total") == provider.group_name
    finally:
        MetricGroupProviderRegistry.unregister(provider.group_name)
