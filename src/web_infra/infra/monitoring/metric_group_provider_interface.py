"""
自定义指标分组 SPI 接口

@Author: 花海
@Date: 2026/08/14 22:00
@Description: 自定义指标采集与展示的服务提供者接口（SPI）：
              业务侧自行创建 Prometheus 指标（沿用 monitoring.metrics 风格），实现本接口
              声明「分组名 + 指标名前缀」，并注册到 MetricGroupProviderRegistry，
              监控可视化页面会自动将匹配指标归入该分组展示，无需改动框架代码。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar


class MetricGroupProviderInterface(ABC):
    """自定义指标分组 SPI 接口"""

    #: 分组名（可视化页面导航与折叠区块标题）
    group_name: ClassVar[str]
    #: 指标名匹配前缀，命中任一前缀即归入该分组
    metric_prefixes: ClassVar[tuple[str, ...]]

    @abstractmethod
    def series_label_zh(self, display_name: str, labels: tuple[tuple[str, str], ...]) -> str | None:
        """将指标某个 series 的标签组合翻译为中文说明。

        直方图/明细展示时用于可读性优化（如将 status=success 译为「成功」）；
        返回 None 表示使用默认的 k=v 格式展示。

        :param display_name: 指标完整展示名（如 biz_order_total）
        :param labels: (标签名, 标签值) 元组列表
        :return: 中文说明；无法翻译时返回 None
        """
        raise NotImplementedError
