"""
并发访问能力静态估算器

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 静态估算器（设计文档《并发访问能力评估设计.md》§4）：基于硬件（CPU 核数探测 +
              配置覆盖）与装配配置（线程池/连接池/限流），推算各维度并发上限（§4.2）、
              按瓶颈模型取 min 得到整体并发上限（§4.3）、经 Little's Law 得理论 QPS、
              乘安全系数得安全水位（§4.4），并做限流/SLO 反推（§4.5）。
              零 I/O（仅读 Settings 与 os.cpu_count），可离线/CLI 运行；运行时实测值
              由 RuntimeSampler 提供并在评估编排中衔接（双轨结合）。
"""
from __future__ import annotations

import os

from web_infra.capabilities.capacity.capacity_config import CapacityConfig
from web_infra.capabilities.capacity.report import ComponentCapacity, StaticEstimation
from web_infra.infra.config.settings import Settings


class StaticEstimator:
    """静态估算器：逐组件并发上限 → 瓶颈模型 → Little's Law → 安全水位 → 限流/SLO 反推"""

    def __init__(self, settings: Settings, config: CapacityConfig) -> None:
        """初始化估算器。

        :param settings: 统一配置门面（读取线程池/连接池/限流等装配参数）
        :param config: 容量评估配置（app.capacity 段）
        """
        self._settings = settings
        self._config = config

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    def estimate(self) -> StaticEstimation:
        """执行静态估算，返回不可变报告快照。

        各维度无法评估（组件未装配/无配置）时 concurrency_limit 记 None 且不参与瓶颈 min；
        整体并发上限取可评估维度的最小值；全部不可评估时返回空静态报告（供上层标注）。
        """
        cpu_cores = self._cpu_cores()
        components = self._component_capacities(cpu_cores)
        limits = [c.concurrency_limit for c in components if c.concurrency_limit is not None]
        concurrency_limit = min(limits) if limits else None

        theoretical_max_qps = None
        latency_s = self._config.assumed_avg_latency_ms / 1000.0
        if concurrency_limit is not None and latency_s > 0:
            theoretical_max_qps = concurrency_limit / latency_s

        safe_qps = theoretical_max_qps * self._config.safe_ratio if theoretical_max_qps is not None else None
        rate_limit_qps = self._rate_limit_qps()
        effective_max_qps = None
        rate_limit_limited = False
        if theoretical_max_qps is not None and rate_limit_qps is not None:
            effective_max_qps = min(theoretical_max_qps, rate_limit_qps)
            rate_limit_limited = rate_limit_qps < theoretical_max_qps
        elif theoretical_max_qps is not None:
            effective_max_qps = theoretical_max_qps

        return StaticEstimation(
            components=tuple(components),
            concurrency_limit=concurrency_limit,
            bottleneck=self._bottleneck_name(components, concurrency_limit),
            theoretical_max_qps=self._round(theoretical_max_qps),
            safe_qps=self._round(safe_qps),
            rate_limit_qps=rate_limit_qps,
            effective_max_qps=self._round(effective_max_qps),
            rate_limit_limited=rate_limit_limited,
            allowed_error_ratio=self._round(1.0 - self._config.slo_target_availability),
            cpu_cores=cpu_cores,
            assumed_avg_latency_ms=self._config.assumed_avg_latency_ms,
        )

    # ------------------------------------------------------------------
    # 内部：各维度并发上限
    # ------------------------------------------------------------------

    def _component_capacities(self, cpu_cores: int) -> list[ComponentCapacity]:
        """逐组件并发上限（§4.2）：web / mysql / redis / mongo / cpu。

        仅装配的组件计入（按 type/enabled 判定，避免把未启用组件当瓶颈）：
        - mysql：app.db.type=mysql 且配置了 pool_size；
        - redis：app.cache.type=redis 且配置了 max_connections；
        - mongo：app.mongo.enabled=true 且配置了 max_pool_size；
        cpu 维度始终可评估（基于核数探测 + 配置覆盖）。
        """
        components: list[ComponentCapacity] = []
        web = self._web_concurrency(cpu_cores)
        if web is not None:
            components.append(ComponentCapacity("web", web, "workers × threads_per_worker"))
        if self._settings.get("app.db.type") == "mysql":
            mysql = self._pool_size("app.db.mysql.pool_size")
            if mysql is not None:
                components.append(ComponentCapacity("mysql", mysql, "MySQL 连接池 pool_size"))
        if self._settings.get("app.cache.type") == "redis":
            redis = self._pool_size("app.cache.redis.max_connections")
            if redis is not None:
                components.append(ComponentCapacity("redis", redis, "Redis 连接池 max_connections"))
        if self._settings.get_bool("app.mongo.enabled"):
            mongo = self._pool_size("app.mongo.max_pool_size")
            if mongo is not None:
                components.append(ComponentCapacity("mongo", mongo, "MongoDB 连接池 max_pool_size"))
        cpu = self._cpu_concurrency(cpu_cores)
        components.append(ComponentCapacity("cpu", cpu, self._cpu_description()))
        return components

    def _web_concurrency(self, cpu_cores: int) -> int | None:
        """Web 层并发上限：workers × threads_per_worker。

        未配置 worker 数时按 CPU 核数估算 1 worker/核（§4.2）；threads_per_worker 缺省
        按 IO 密集系数估算（与 cpu 维度口径一致：异步框架单 worker 事件循环可承载多并发，
        避免线程数=1 使 web 恒成瓶颈）。
        """
        workers = self._settings.get("app.uvicorn.workers") or self._settings.get("app.server.workers")
        if workers is None:
            workers = cpu_cores
        threads_per_worker = self._settings.get("app.uvicorn.threads") or self._settings.get("app.server.threads")
        if threads_per_worker is None:
            threads_per_worker = self._config.io_concurrency_factor
        try:
            return int(workers) * int(threads_per_worker)
        except (TypeError, ValueError):
            return None

    def _pool_size(self, key: str) -> int | None:
        """读取连接池上限配置（MySQL pool_size / Redis max_connections / Mongo max_pool_size）。"""
        try:
            value = self._settings.get(key)
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _cpu_concurrency(self, cpu_cores: int) -> int:
        """CPU 维度并发上限：IO 密集 = 核数 × io_concurrency_factor；CPU 密集 = 核数（§4.2）。"""
        if self._config.workload_type == "cpu_intensive":
            return cpu_cores
        return cpu_cores * self._config.io_concurrency_factor

    def _cpu_description(self) -> str:
        """CPU 维度计算口径说明（供报告可读）"""
        if self._config.workload_type == "cpu_intensive":
            return f"CPU 密集：核数 {self._cpu_cores()}（每核一个请求）"
        return (
            f"IO 密集：核数 {self._cpu_cores()} × io_concurrency_factor "
            f"{self._config.io_concurrency_factor}"
        )

    def _cpu_cores(self) -> int:
        """CPU 核数：配置覆盖优先，否则 os.cpu_count()（探测失败回落 1）。"""
        if self._config.cpu_cores is not None and self._config.cpu_cores > 0:
            return self._config.cpu_cores
        return os.cpu_count() or 1

    # ------------------------------------------------------------------
    # 内部：限流反推 / 瓶颈
    # ------------------------------------------------------------------

    def _rate_limit_qps(self) -> float | None:
        """限流器 QPS 上限（§4.5 限流反推）：读取 app.web.middlewares.rate_limit.qps。

        仅当 rate_limit 中间件启用（配置存在且未显式关闭）时反推；未启用返回 None（不限流）。
        """
        rate_limit = self._settings.get("app.web.middlewares.rate_limit")
        if not isinstance(rate_limit, dict) or rate_limit.get("enabled") is False:
            return None
        qps = rate_limit.get("qps")
        try:
            return float(qps) if qps is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bottleneck_name(components: list[ComponentCapacity], concurrency_limit: int | None) -> str | None:
        """瓶颈组件名：并发上限最小的维度（§4.3）；无法评估时 None。"""
        if concurrency_limit is None:
            return None
        candidates = [c for c in components if c.concurrency_limit is not None]
        if not candidates:
            return None
        return min(candidates, key=lambda c: c.concurrency_limit).name

    @staticmethod
    def _round(value: float | None, ndigits: int = 2) -> float | None:
        """数值四舍五入（None 透传，避免报告出现长尾小数）"""
        return round(value, ndigits) if value is not None else None
