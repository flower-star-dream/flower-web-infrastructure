"""
容量评估 Prometheus 指标

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 容量评估指标（设计文档《并发访问能力评估设计.md》§7.4）：capacity_ 前缀 Gauge
              随 /metrics 暴露，供 Grafana 等外部监控消费。由评估编排（CapacityAssessor）
              每次采样后刷新——静态区（理论 QPS/安全水位）在评估时刷新，运行时区（当前
              QPS/并发/利用率/瓶颈）随采样任务刷新；指标注册于模块级（prometheus 全局
              注册表），未启用评估能力时指标不更新但注册表已有（无样本不展示）。
"""
from __future__ import annotations

from prometheus_client import Gauge

# 静态区：理论最大 QPS / 安全水位 QPS（§7.4，由静态估算结果刷新）
CAPACITY_THEORETICAL_MAX_QPS = Gauge("capacity_theoretical_max_qps", "理论最大 QPS（Little's Law）")
CAPACITY_SAFE_QPS = Gauge("capacity_safe_qps", "安全水位 QPS（理论 QPS × safe_ratio）")
# 运行时区：当前 QPS / 当前并发 / 利用率 / 瓶颈组件（label=component 值 1）
CAPACITY_CURRENT_QPS = Gauge("capacity_current_qps", "当前 QPS（滑动窗口最近样本）")
CAPACITY_CURRENT_CONCURRENCY = Gauge("capacity_current_concurrency", "当前并发（in-flight 请求数）")
CAPACITY_UTILIZATION_RATIO = Gauge("capacity_utilization_ratio", "利用率 = 当前 QPS ÷ 理论 QPS（0~1）")
CAPACITY_BOTTLENECK = Gauge("capacity_bottleneck", "瓶颈组件（label=component，值 1）", ["component"])


def refresh_static_gauges(theoretical_max_qps: float | None, safe_qps: float | None) -> None:
    """刷新静态区 Gauge（理论 QPS / 安全水位）。

    :param theoretical_max_qps: 理论最大 QPS（None 时置 0，避免悬空旧值）
    :param safe_qps: 安全水位 QPS（None 时置 0）
    """
    CAPACITY_THEORETICAL_MAX_QPS.set(theoretical_max_qps if theoretical_max_qps is not None else 0.0)
    CAPACITY_SAFE_QPS.set(safe_qps if safe_qps is not None else 0.0)


def refresh_runtime_gauges(
    current_qps: float | None,
    current_concurrency: float | None,
    utilization_ratio: float | None,
    bottleneck: str | None,
) -> None:
    """刷新运行时区 Gauge（当前 QPS/并发/利用率/瓶颈组件）。

    :param current_qps: 当前 QPS（None 时置 0）
    :param current_concurrency: 当前并发（None 时置 0）
    :param utilization_ratio: 利用率 0~1（None 时置 0）
    :param bottleneck: 瓶颈组件名（None 时清空全部标签，避免悬垂标签）
    """
    CAPACITY_CURRENT_QPS.set(current_qps if current_qps is not None else 0.0)
    CAPACITY_CURRENT_CONCURRENCY.set(current_concurrency if current_concurrency is not None else 0.0)
    CAPACITY_UTILIZATION_RATIO.set(utilization_ratio if utilization_ratio is not None else 0.0)
    CAPACITY_BOTTLENECK.clear()
    if bottleneck:
        CAPACITY_BOTTLENECK.labels(bottleneck).set(1.0)
