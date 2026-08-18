"""
并发访问能力评估编排器

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 评估编排器（设计文档《并发访问能力评估设计.md》§7.2/§8）：组合静态估算器
              （StaticEstimator）、运行时采样器（RuntimeSampler）与远程探针（RemoteProbe），
              产出统一 CapacityReport（静态 + 运行时 + 集群 + 建议）。管理采样任务生命周期
              （asyncio 后台循环，startup 启动 / shutdown 取消），每次采样后刷新
              Prometheus Gauge（capacity_metrics）；/capacity 请求时窗口为空先即时补采一次。
              建议生成覆盖：瓶颈提示、限流受限、SLO 风险、运行时数据不足。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from web_infra.capabilities.capacity.capacity_config import CapacityConfig
from web_infra.capabilities.capacity.capacity_metrics import refresh_runtime_gauges, refresh_static_gauges
from web_infra.capabilities.capacity.remote_probe import RemoteProbe
from web_infra.capabilities.capacity.report import CapacityReport, RuntimeSnapshot
from web_infra.capabilities.capacity.runtime_sampler import RuntimeSampler
from web_infra.capabilities.capacity.static_estimator import StaticEstimator
from web_infra.infra.config.settings import Settings

logger = logging.getLogger(__name__)


class CapacityAssessor:
    """容量评估编排器：静态 + 运行时 + 集群三源组合，产出 CapacityReport 并刷新 Gauge"""

    def __init__(self, settings: Settings, config: CapacityConfig) -> None:
        """初始化评估器。

        :param settings: 统一配置门面（静态估算读装配参数）
        :param config: 容量评估配置（app.capacity 段）
        """
        self._config = config
        self._estimator = StaticEstimator(settings, config)
        self._sampler = RuntimeSampler(config)
        self._probe = RemoteProbe(config.remote)
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # 采样任务生命周期（Application lifespan 编排）
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动后台采样任务（asyncio 循环，非阻塞；重复调用幂等）。"""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop(), name="capacity-sampler")

    async def stop(self) -> None:
        """停止采样任务（取消并等待退出，幂等）。"""
        if self._task is None:
            return
        task, self._task = self._task, None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run_loop(self) -> None:
        """采样循环：每 sample_interval 秒采样一次并刷新 Gauge（含静态区一次）"""
        static = self._estimator.estimate()
        refresh_static_gauges(static.theoretical_max_qps, static.safe_qps)
        while True:
            snapshot = self._sampler.sample()
            self._refresh_runtime_gauges(snapshot, static.theoretical_max_qps, static.bottleneck)
            await asyncio.sleep(max(self._config.sample_interval, 0.1))

    # ------------------------------------------------------------------
    # 对外评估入口
    # ------------------------------------------------------------------

    async def assess(self, include_cluster: bool = True) -> CapacityReport:
        """生成完整评估报告。

        :param include_cluster: 是否拉取集群视图（CLI 未配 --remote 时传 False，
            避免无谓网络开销）
        :return: 统一评估报告（静态 + 运行时 + 可选集群 + 建议）
        """
        static = self._estimator.estimate()
        refresh_static_gauges(static.theoretical_max_qps, static.safe_qps)

        runtime = self._sampler.snapshot()
        if runtime.sample_count == 0:
            # 窗口为空：即时补采一次，保证首次访问即有数据（§5）
            runtime = self._sampler.sample()
        self._refresh_runtime_gauges(runtime, static.theoretical_max_qps, static.bottleneck)

        cluster = await self._probe.evaluate(self._config.remote_targets) if include_cluster else None

        utilization = self._utilization(runtime.current_qps, static.theoretical_max_qps)
        suggestions = self._build_suggestions(static, runtime, cluster)

        return CapacityReport(
            static=static,
            runtime=runtime,
            cluster=cluster,
            utilization_ratio=utilization,
            suggestions=tuple(suggestions),
        )

    def assess_static_only(self) -> CapacityReport:
        """仅静态估算（CLI 无运行进程场景，§7.3）：运行时区标注 None。"""
        static = self._estimator.estimate()
        return CapacityReport(static=static, runtime=None, cluster=None, utilization_ratio=None)

    # ------------------------------------------------------------------
    # 内部：利用率 / 建议 / Gauge
    # ------------------------------------------------------------------

    @staticmethod
    def _utilization(current_qps: float | None, theoretical_max_qps: float | None) -> float | None:
        """利用率 = 当前 QPS ÷ 理论 QPS（0~1 封顶）；任一缺失返回 None。"""
        if current_qps is None or theoretical_max_qps is None or theoretical_max_qps <= 0:
            return None
        return round(min(current_qps / theoretical_max_qps, 1.0), 4)

    def _build_suggestions(
        self,
        static: Any,
        runtime: RuntimeSnapshot,
        cluster: Any,
    ) -> list[str]:
        """生成建议列表（§7.1）：瓶颈 / 限流受限 / SLO 风险 / 数据不足 / 集群不可达。"""
        suggestions: list[str] = []
        if static.bottleneck is not None:
            suggestions.append(f"瓶颈组件：{static.bottleneck}（并发上限 {static.concurrency_limit}）")
        if static.rate_limit_limited and static.effective_max_qps is not None:
            suggestions.append(f"受限于限流配置（qps={static.rate_limit_qps}），理论可达 {static.theoretical_max_qps}")
        if (
            runtime.sample_count > 0
            and runtime.error_ratio is not None
            and static.allowed_error_ratio > 0
            and runtime.error_ratio >= static.allowed_error_ratio * self._config.slo_alert_ratio
        ):
            suggestions.append(
                f"SLO 风险：错误率 {runtime.error_ratio} ≥ 允许值 "
                f"{static.allowed_error_ratio} × {self._config.slo_alert_ratio}"
            )
        if runtime.sample_count == 0:
            suggestions.append("运行时数据不足：采样窗口为空，仅静态估算（请求 /capacity 将触发即时补采）")
        if cluster is not None and cluster.instance_count > 0:
            if cluster.all_unreachable:
                suggestions.append("集群全部实例不可达：请检查网络与 remote_targets 配置")
            elif cluster.unreachable_count > 0:
                suggestions.append(f"集群 {cluster.unreachable_count}/{cluster.instance_count} 实例不可达")
        return suggestions

    def _refresh_runtime_gauges(
        self,
        snapshot: RuntimeSnapshot,
        theoretical_max_qps: float | None,
        bottleneck: str | None,
    ) -> None:
        """刷新运行时区 Gauge（当前 QPS/并发/利用率/瓶颈）。"""
        utilization = self._utilization(snapshot.current_qps, theoretical_max_qps)
        refresh_runtime_gauges(
            snapshot.current_qps,
            snapshot.current_concurrency,
            utilization,
            bottleneck,
        )
