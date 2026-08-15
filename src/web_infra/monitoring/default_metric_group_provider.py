"""
默认指标分组提供者

@Author: 花海
@Date: 2026/08/15 10:00
@Description: MetricGroupProviderInterface 的默认实现（规范 S3-2：扩展点必须提供默认实现）：
              提供 group(metric_name) 程序化分组能力——按指标名前缀分组
              （web_*→web、db_*→db、mq_*→mq、ai_*→ai、cache_*→cache，其余→other），
              支持构造参数 group_map 自定义「前缀 → 组名」映射；
              同时实现 SPI 接口（group_name/metric_prefixes/series_label_zh），
              可作为兜底提供者注册到 MetricGroupProviderRegistry（默认归入 other 组，
              覆盖默认前缀集合），业务无自定义分组实现时无需改动框架代码。
"""
from __future__ import annotations

from typing import ClassVar

from web_infra.monitoring.metric_group_provider_interface import MetricGroupProviderInterface


class DefaultMetricGroupProvider(MetricGroupProviderInterface):
    """默认指标分组提供者：按指标名前缀映射分组（规范 S3-2 默认实现）"""

    #: 默认「指标名前缀 → 分组名」映射（构造参数 group_map 为 None 时使用）
    DEFAULT_GROUP_MAP: ClassVar[dict[str, str]] = {
        "web_": "web",
        "db_": "db",
        "mq_": "mq",
        "ai_": "ai",
        "cache_": "cache",
    }
    #: 默认分组名（未命中任何前缀时归入该组）
    DEFAULT_GROUP_NAME: ClassVar[str] = "other"

    #: SPI 分组名（与 MetricGroupProviderInterface 类变量语义一致）
    group_name: ClassVar[str] = DEFAULT_GROUP_NAME
    #: SPI 指标名前缀集合（默认映射的全部前缀）
    metric_prefixes: ClassVar[tuple[str, ...]] = tuple(DEFAULT_GROUP_MAP.keys())

    def __init__(self, group_map: dict[str, str] | None = None) -> None:
        """初始化默认指标分组提供者。

        :param group_map: 自定义「指标名前缀 → 分组名」映射，覆盖默认映射；None 使用默认映射
        """
        self._group_map = dict(self.DEFAULT_GROUP_MAP if group_map is None else group_map)

    def group(self, metric_name: str) -> str:
        """按指标名前缀返回所属分组名；未命中任何前缀返回默认分组名（other）。

        :param metric_name: 指标完整展示名（如 web_http_requests_total）
        :return: 分组名（如 web / db / other）
        """
        for prefix, group in self._group_map.items():
            if metric_name == prefix or metric_name.startswith(prefix):
                return group
        return self.DEFAULT_GROUP_NAME

    def series_label_zh(self, display_name: str, labels: tuple[tuple[str, str], ...]) -> str | None:
        """默认提供者不提供 series 标签中文翻译，返回 None 走默认 k=v 格式展示。"""
        return None
