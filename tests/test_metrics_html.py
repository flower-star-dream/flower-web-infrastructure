"""
指标可视化页面与自定义分组 SPI 单元测试

@Author: 花海
@Date: 2026/08/14 22:00
@Description: 验证 /metrics HTML 渲染（内置分组/概览卡/分位数估算）、内容协商判断、
              分组按样本动态渲染（未启用组件不展现）、以及自定义指标分组 SPI 的注册与页面归组展示。
"""
from concurrent.futures import ThreadPoolExecutor

from prometheus_client import Counter

from web_infra.infra.monitoring import (
    CacheMetrics,
    MqMetrics,
    RegistryMetrics,
    StorageMetrics,
    ai_metrics,
    metrics,
)
from web_infra.infra.monitoring.metric_group_provider_interface import MetricGroupProviderInterface
from web_infra.infra.monitoring.metric_group_provider_registry import MetricGroupProviderRegistry
from web_infra.infra.monitoring.metrics_html import (
    _group_has_data,
    histogram_quantile,
    render_metrics_html,
    should_render_html,
)
from web_infra.infra.monitoring.pool_metrics import (
    record_mongo_pool_metrics,
    record_mysql_pool_metrics,
    record_redis_pool_metrics,
)
from web_infra.infra.monitoring.runtime_metrics import ThreadPoolMetrics, record_runtime_metrics


class _FakePool:
    """模拟 SQLAlchemy QueuePool（total/checkedout）"""

    def __init__(self, total: int, checkedout: int) -> None:
        self._total = total
        self._checkedout = checkedout

    def total(self) -> int:
        return self._total

    def checkedout(self) -> int:
        return self._checkedout


class _FakeRedisClient:
    """模拟 redis.asyncio 客户端（仅连接池内部属性）"""

    def __init__(self, created: int, in_use: int, max_connections: int) -> None:
        class _Pool:
            def __init__(self) -> None:
                self._created_connections = created
                self._in_use_connections = [None] * in_use
                self._available_connections = [None] * (created - in_use)
                self.max_connections = max_connections

        self.connection_pool = _Pool()


class _FakeMongoConfig:
    """模拟 MongoDBConfig（仅池上限与客户端）"""

    max_pool_size = 50
    client = None


def _seed_all_groups() -> None:
    """为全部内置分组制造实际样本，验证页面按分组完整渲染"""
    metrics.init_metrics("test")
    metrics.record_http_request("GET", "/api/orders", 0.1, 200)
    metrics.record_slow_sql("default", 0.3, "SELECT 1", "warning", "P2")
    metrics.SLOW_SQL_TOTAL.labels("test", "default", "warning").inc(1)
    metrics.REQUEST_PHASE_DURATION_SECONDS.labels("test", "gateway").observe(0.01)
    record_mysql_pool_metrics(_FakePool(total=5, checkedout=2), "default")
    record_redis_pool_metrics(_FakeRedisClient(created=8, in_use=3, max_connections=50), "default")
    record_mongo_pool_metrics(_FakeMongoConfig(), "default")
    CacheMetrics.record_operation("memory", "get", hit=True)
    StorageMetrics.record_operation("local", "put", bytes_count=1024)
    MqMetrics.record_published("order")
    MqMetrics.update_pending("memory", 3)
    RegistryMetrics.record_register("user-service")
    RegistryMetrics.update_instances("user-service", 2)
    ThreadPoolMetrics.register(ThreadPoolExecutor(max_workers=2), "test-pool")
    ThreadPoolMetrics.collect()
    record_runtime_metrics()
    ai_metrics.init_ai_metrics("test")
    ai_metrics.record_ai_call("deepseek", "success")


def test_should_render_html_precedence():
    """内容协商优先级：format 参数 > Accept 头"""
    assert should_render_html("text", "text/html") is False
    assert should_render_html("text", None) is False
    assert should_render_html("html", None) is True
    assert should_render_html("html", "text/plain") is True
    assert should_render_html(None, "text/html") is True
    assert should_render_html(None, "text/html,application/xhtml+xml") is True
    assert should_render_html(None, "*/*") is False
    assert should_render_html(None, None) is False


def test_histogram_quantile_interpolation():
    """分位数估算：桶内线性插值"""
    buckets = [(0.1, 5), (0.5, 20), (1.0, 30), (float("inf"), 40)]
    # rank=20 落在 (0.1, 0.5] 桶：0.1 + 0.4 * (20-5) / (20-5) = 0.5
    assert abs(histogram_quantile(buckets, 0.5) - 0.5) < 1e-9
    # rank=30 落在 (0.5, 1.0] 桶：0.5 + 0.5 * (30-20) / (30-20) = 1.0
    assert abs(histogram_quantile(buckets, 0.75) - 1.0) < 1e-9
    # rank=38 落入 +Inf 桶：算法返回 +Inf（与 Prometheus histogram_quantile 行为一致）
    assert histogram_quantile(buckets, 0.95) == float("inf")


def test_histogram_quantile_empty_or_invalid():
    """空样本 / 非法分位数返回 None"""
    assert histogram_quantile([], 0.95) is None
    assert histogram_quantile([(1.0, 0)], 0.95) is None
    assert histogram_quantile([(1.0, 5)], 1.5) is None


def test_group_has_data():
    """分组数据判定：有任一非空样本才算有数据"""
    from prometheus_client import REGISTRY

    probe = Counter("probe_empty_has_data", "x", ["l"])  # 注册但无样本

    def _collect(name: str):
        for metric in REGISTRY.collect():
            if metric.name == name:
                return metric
        return None

    assert _group_has_data([("probe_empty_has_data", _collect("probe_empty_has_data"))]) is False
    probe.labels("a").inc(1)
    assert _group_has_data([("probe_empty_has_data", _collect("probe_empty_has_data"))]) is True


def test_render_metrics_html_builtin_groups():
    """全部内置分组制造样本后完整渲染，且概览统计卡齐全"""
    _seed_all_groups()
    html = render_metrics_html("test-service", theme="light")
    assert "指标总览" in html
    assert "test-service" in html
    for group in [
        "HTTP RED 指标",
        "全链路分阶段耗时",
        "慢请求 / 慢 SQL",
        "MySQL 连接池",
        "Redis / MongoDB 连接池",
        "缓存指标",
        "消息队列指标",
        "对象存储指标",
        "注册中心指标",
        "线程池",
        "Python 运行时",
        "AI 模型指标",
    ]:
        assert group in html
    for card in ["总请求", "当前并发", "错误数", "平均耗时", "慢请求", "慢 SQL", "AI 调用"]:
        assert card in html


def test_group_dynamic_rendering_by_samples():
    """分组按样本动态渲染：指标注册但无样本不展现，产生样本后才展现（配置动态决定）"""
    probe = Counter("probe_dynamic_group_total", "探针指标", ["l"])
    MetricGroupProviderRegistry.register(_ProbeProvider())
    try:
        html = render_metrics_html("app", theme="light")
        assert "探针指标" not in html  # 注册但无样本 → 分组隐藏

        probe.labels("x").inc(1)
        html = render_metrics_html("app", theme="light")
        assert "探针指标" in html  # 产生样本 → 分组展示
    finally:
        MetricGroupProviderRegistry.unregister("探针指标")


class _ProbeProvider(MetricGroupProviderInterface):
    """测试用 SPI：探针指标分组（验证按样本动态渲染）"""

    group_name = "探针指标"
    metric_prefixes = ("probe_dynamic_",)

    def series_label_zh(self, display_name, labels):
        return None


class _BizOrderProvider(MetricGroupProviderInterface):
    """测试用 SPI：业务订单指标分组"""

    group_name = "业务指标"
    metric_prefixes = ("biz_order_",)

    def series_label_zh(self, display_name, labels):
        if display_name == "biz_order_total":
            for k, v in labels:
                if k == "status" and v == "paid":
                    return "状态=已支付"
        return None


def test_spi_registry_group_matching():
    """SPI 注册表：按指标名前缀匹配分组，未命中返回 None"""
    MetricGroupProviderRegistry.register(_BizOrderProvider())
    try:
        assert MetricGroupProviderRegistry.group_of("biz_order_total") == "业务指标"
        assert MetricGroupProviderRegistry.group_of("biz_order_count") == "业务指标"
        assert MetricGroupProviderRegistry.group_of("http_requests_total") is None
    finally:
        MetricGroupProviderRegistry.unregister("业务指标")


def test_spi_registry_requires_group_fields():
    """注册缺少分组名/前缀的提供者应抛 ValueError"""
    try:
        MetricGroupProviderRegistry.register(_InvalidProvider())
        assert False, "应抛 ValueError"
    except ValueError:
        pass


class _InvalidProvider(MetricGroupProviderInterface):
    """缺少 metric_prefixes 的非法提供者"""

    group_name = "非法分组"
    metric_prefixes = ()

    def series_label_zh(self, display_name, labels):
        return None


def test_render_metrics_html_with_spi_group():
    """SPI 分组指标自动出现在页面并采用中文标签说明"""
    MetricGroupProviderRegistry.register(_BizOrderProvider())
    biz_order_total = Counter("biz_order_total", "业务订单数", ["status"])
    biz_order_total.labels("paid").inc(3)
    try:
        html = render_metrics_html("app", theme="light")
        assert "业务指标" in html
        assert "biz_order_total" in html
        assert "状态=已支付" in html
    finally:
        MetricGroupProviderRegistry.unregister("业务指标")
