"""
并发访问能力评估报告数据模型

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 容量评估报告的数据模型（设计文档《并发访问能力评估设计.md》§7.1）：
              静态估算（逐组件并发上限/理论 QPS/安全水位/瓶颈/限流·SLO 反推）、
              运行时状态（当前 QPS/并发/CPU、窗口峰值、利用率）、集群视图（实例状态/QPS 分布）
              与建议。全部为不可变快照（frozen dataclass），供 /capacity 端点、HTML 页面、
              CLI 与 Prometheus Gauge 消费，四类输出共用同一模型。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ComponentCapacity:
    """逐组件并发上限（瓶颈分析的最小单元，§4.2）

    :param name: 组件维度名（web / mysql / redis / mongo / cpu）
    :param concurrency_limit: 该维度并发上限；无法评估时 None（如组件未装配）
    :param description: 计算口径说明（含配置来源/默认值），便于报告可读
    """

    name: str
    concurrency_limit: int | None
    description: str = ""


@dataclass(frozen=True)
class StaticEstimation:
    """静态估算结果（§4：Little's Law / 瓶颈模型 / 安全水位 / 限流·SLO 反推）

    :param components: 逐组件并发上限列表（按维度）
    :param concurrency_limit: 整体并发上限 = min(各组件)，瓶颈模型
    :param bottleneck: 瓶颈组件名（并发上限最小的维度）；无法评估时 None
    :param theoretical_max_qps: 理论最大 QPS（Little's Law：并发上限 ÷ 平均响应时间）
    :param safe_qps: 安全水位 QPS（理论 QPS × safe_ratio）
    :param rate_limit_qps: 限流器 QPS 上限（RateLimitConfig.qps；未启用限流时 None）
    :param effective_max_qps: 配置支撑的最大 QPS = min(理论 QPS, 限流 qps)
    :param rate_limit_limited: 是否受限于限流配置（限流 qps < 理论 QPS）
    :param allowed_error_ratio: 允许错误率（1 - target_availability，SLO 反推用）
    :param cpu_cores: 评估用的 CPU 核数（探测或配置覆盖）
    :param assumed_avg_latency_ms: Little's Law 用的平均响应时间假设（毫秒）
    """

    components: tuple[ComponentCapacity, ...] = ()
    concurrency_limit: int | None = None
    bottleneck: str | None = None
    theoretical_max_qps: float | None = None
    safe_qps: float | None = None
    rate_limit_qps: float | None = None
    effective_max_qps: float | None = None
    rate_limit_limited: bool = False
    allowed_error_ratio: float = 0.01
    cpu_cores: int | None = None
    assumed_avg_latency_ms: float = 200.0

    def as_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化字典（供 /capacity JSON 与 CLI 输出）"""
        return {
            "components": [c.__dict__ for c in self.components],
            "concurrency_limit": self.concurrency_limit,
            "bottleneck": self.bottleneck,
            "theoretical_max_qps": self.theoretical_max_qps,
            "safe_qps": self.safe_qps,
            "rate_limit_qps": self.rate_limit_qps,
            "effective_max_qps": self.effective_max_qps,
            "rate_limit_limited": self.rate_limit_limited,
            "allowed_error_ratio": self.allowed_error_ratio,
            "cpu_cores": self.cpu_cores,
            "assumed_avg_latency_ms": self.assumed_avg_latency_ms,
        }


@dataclass(frozen=True)
class RuntimeSnapshot:
    """运行时窗口快照（§5 滑动窗口：均值/峰值 + 当前值）

    :param current_qps: 窗口最近一次采样的 QPS；无样本时 None
    :param current_concurrency: 窗口最近一次采样的并发；无样本时 None
    :param current_cpu_percent: 窗口最近一次采样的 CPU 占用（%）；不可用时 None
    :param qps_mean/qps_peak: 窗口内 QPS 均值/峰值
    :param concurrency_mean/concurrency_peak: 窗口内并发均值/峰值
    :param cpu_mean/cpu_peak: 窗口内 CPU 均值/峰值
    :param error_ratio: 窗口内错误率（5xx 请求占比）；无样本时 None
    :param latency_p50/latency_p95: 窗口内延迟分位数（秒）；无样本时 None
    :param sample_count: 窗口内有效样本数
    """

    current_qps: float | None = None
    current_concurrency: float | None = None
    current_cpu_percent: float | None = None
    qps_mean: float | None = None
    qps_peak: float | None = None
    concurrency_mean: float | None = None
    concurrency_peak: float | None = None
    cpu_mean: float | None = None
    cpu_peak: float | None = None
    error_ratio: float | None = None
    latency_p50: float | None = None
    latency_p95: float | None = None
    sample_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化字典"""
        return {
            "current_qps": self.current_qps,
            "current_concurrency": self.current_concurrency,
            "current_cpu_percent": self.current_cpu_percent,
            "qps_mean": self.qps_mean,
            "qps_peak": self.qps_peak,
            "concurrency_mean": self.concurrency_mean,
            "concurrency_peak": self.concurrency_peak,
            "cpu_mean": self.cpu_mean,
            "cpu_peak": self.cpu_peak,
            "error_ratio": self.error_ratio,
            "latency_p50": self.latency_p50,
            "latency_p95": self.latency_p95,
            "sample_count": self.sample_count,
        }


@dataclass(frozen=True)
class InstanceSnapshot:
    """集群单实例状态（§6 RemoteProbe 拉取结果）

    :param url: 实例 /metrics 地址
    :param status: ok（拉取成功）/ unreachable（失败，含失败原因分类）
    :param qps: 该实例差分 QPS；无数据（首次/差分不足）时 None
    :param error: 失败原因（HTTP 状态 / 超时 / 连接失败 / 解析失败等可读描述）；成功时 None
    """

    url: str
    status: str = "ok"
    qps: float | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化字典"""
        return {"url": self.url, "status": self.status, "qps": self.qps, "error": self.error}


@dataclass(frozen=True)
class ClusterSnapshot:
    """集群视图（§6 聚合输出）

    :param instances: 各实例状态列表（含本实例之外的 remote_targets）
    :param total_qps: 集群总 QPS（全部成功实例 QPS 之和）；无实例或全不可达时 None
    :param instance_count: 配置的实例总数（含不可达）
    :param unreachable_count: 不可达实例数
    """

    instances: tuple[InstanceSnapshot, ...] = ()
    total_qps: float | None = None
    instance_count: int = 0
    unreachable_count: int = 0

    @property
    def all_unreachable(self) -> bool:
        """是否全部实例不可达（CLI 退出码 2 判定，§6.2）"""
        return self.instance_count > 0 and self.unreachable_count == self.instance_count

    def as_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化字典"""
        return {
            "instances": [i.as_dict() for i in self.instances],
            "total_qps": self.total_qps,
            "instance_count": self.instance_count,
            "unreachable_count": self.unreachable_count,
            "all_unreachable": self.all_unreachable,
        }


@dataclass(frozen=True)
class CapacityReport:
    """容量评估报告（四类输出共用，§7.1）

    :param generated_at: 报告生成时间（ISO 格式，本地时区）
    :param static: 静态估算结果
    :param runtime: 运行时快照；CLI 无运行进程时为 None（§7.3）
    :param cluster: 集群视图；未配置 remote_targets 时为 None
    :param utilization_ratio: 利用率 = 当前 QPS ÷ 理论 QPS（0~1）；数据不足时 None
    :param suggestions: 建议列表（瓶颈提示 / 限流受限 / SLO 风险 / 数据不足等）
    """

    generated_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    static: StaticEstimation = field(default_factory=StaticEstimation)
    runtime: RuntimeSnapshot | None = None
    cluster: ClusterSnapshot | None = None
    utilization_ratio: float | None = None
    suggestions: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化字典（/capacity JSON 与 CLI --json 输出）"""
        return {
            "generated_at": self.generated_at,
            "static": self.static.as_dict(),
            "runtime": self.runtime.as_dict() if self.runtime else None,
            "cluster": self.cluster.as_dict() if self.cluster else None,
            "utilization_ratio": self.utilization_ratio,
            "suggestions": list(self.suggestions),
        }
