"""
自定义指标分组 SPI 注册表

@Author: 花海
@Date: 2026/08/14 22:00
@Description: 自定义指标分组注册表（SPI）：业务实现 MetricGroupProviderInterface 并注册后，
              监控可视化页面自动归组展示其指标。注册顺序即页面分组顺序。
"""
from __future__ import annotations

from typing import ClassVar

from web_infra.infra.monitoring.metric_group_provider_interface import MetricGroupProviderInterface


class MetricGroupProviderRegistry:
    """自定义指标分组 SPI 注册表"""

    _providers: ClassVar[list[MetricGroupProviderInterface]] = []

    @classmethod
    def register(cls, provider: MetricGroupProviderInterface) -> MetricGroupProviderInterface:
        """注册一个自定义指标分组提供者（同名分组覆盖），返回该提供者。"""
        if not provider.group_name or not provider.metric_prefixes:
            raise ValueError("自定义指标分组必须声明 group_name 与 metric_prefixes")
        cls._providers = [p for p in cls._providers if p.group_name != provider.group_name]
        cls._providers.append(provider)
        return provider

    @classmethod
    def all(cls) -> tuple[MetricGroupProviderInterface, ...]:
        """返回全部已注册提供者（按注册顺序）。"""
        return tuple(cls._providers)

    @classmethod
    def unregister(cls, group_name: str) -> None:
        """注销指定分组的提供者（测试隔离或运行时动态调整分组时用）。"""
        cls._providers = [p for p in cls._providers if p.group_name != group_name]

    @classmethod
    def group_of(cls, metric_name: str) -> str | None:
        """按指标名前缀返回命中的 SPI 分组名；未命中返回 None。

        :param metric_name: 指标完整展示名
        :return: 分组名或 None
        """
        for provider in cls._providers:
            if any(metric_name == prefix or metric_name.startswith(prefix) for prefix in provider.metric_prefixes):
                return provider.group_name
        return None

    @classmethod
    def provider_of(cls, group_name: str) -> MetricGroupProviderInterface | None:
        """按分组名返回提供者实例（供页面做标签中文映射）；未注册返回 None。"""
        for provider in cls._providers:
            if provider.group_name == group_name:
                return provider
        return None
