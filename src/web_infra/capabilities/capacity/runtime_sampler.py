"""
并发访问能力运行时采样器

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 运行时采样器（设计文档《并发访问能力评估设计.md》§5）：直读 prometheus_client
              进程内指标（REGISTRY.collect()，不新增业务埋点）——QPS（http_requests_total
              Counter 差分）、当前并发（http_requests_in_flight Gauge）、延迟分位数
              （http_request_duration_seconds Histogram bucket 近似）与错误率；CPU 占用
              由跨平台采样器提供（§5.1：Linux /proc/stat、Windows ctypes GetSystemTimes、
              其他平台探测 psutil 否则返回 None）。滑动窗口环形缓冲存储最近样本，
              snapshot() 汇总窗口均值/峰值，供 /capacity 报告与 Prometheus Gauge 消费。
"""
from __future__ import annotations

import os
import sys
import time
from collections import deque
from threading import Lock
from typing import Any

from prometheus_client import REGISTRY

from web_infra.capabilities.capacity.capacity_config import CapacityConfig
from web_infra.capabilities.capacity.report import RuntimeSnapshot
from web_infra.infra.monitoring.metrics_html import histogram_quantile

# 指标名（与 infra.monitoring.metrics 定义一致，直读注册表不依赖具体对象）
_COUNTER_REQUESTS = "http_requests_total"
_GAUGE_IN_FLIGHT = "http_requests_in_flight"
_HISTOGRAM_DURATION = "http_request_duration_seconds"


class CpuSampler:
    """跨平台 CPU 占用采样器（§5.1，零新依赖；不可用时返回 None 优雅降级）。

    基于「两次采样差分」计算占用率，首次采样仅记录基线返回 None；
    读取失败/平台不支持返回 None（仅影响 CPU 维度推断，不影响 QPS/并发评估）。
    """

    def __init__(self) -> None:
        """初始化采样器（无基线，首次采样建立基线）"""
        self._prev_total: float | None = None
        self._prev_busy: float | None = None

    def sample(self) -> float | None:
        """采集当前 CPU 占用率（%）；首次调用/不可用返回 None。

        实现：
        - Linux：解析 /proc/stat 首行（user/nice/system/idle/iowait/irq/softirq/steal），
          busy = total - idle - iowait；占用率 = Δbusy / Δtotal；
        - Windows：ctypes 调 kernel32.GetSystemTimes（idle/kernel/user FILETIME），
          busy = (kernel + user) - idle，total = kernel + user；
        - 其他平台：探测到 psutil 则用 cpu_percent，否则返回 None。
        """
        stats = self._read_stats()
        if stats is None:
            return None
        total, busy = stats
        if self._prev_total is None:
            self._prev_total, self._prev_busy = total, busy
            return None
        delta_total = total - self._prev_total
        delta_busy = busy - self._prev_busy
        self._prev_total, self._prev_busy = total, busy
        if delta_total <= 0:
            return None
        return round(delta_busy / delta_total * 100.0, 2)

    # ------------------------------------------------------------------
    # 平台实现
    # ------------------------------------------------------------------

    def _read_stats(self) -> tuple[float, float] | None:
        """读取 (总时间, 忙时间) 二元组；平台不支持/读取失败返回 None"""
        if sys.platform.startswith("linux"):
            return self._read_linux()
        if sys.platform == "win32":
            return self._read_windows()
        return self._read_psutil()

    @staticmethod
    def _read_linux() -> tuple[float, float] | None:
        """Linux：/proc/stat 首行 cpu 行差分（各字段单位为 USER_HZ 时钟滴答）"""
        try:
            with open("/proc/stat", encoding="utf-8") as f:
                line = f.readline()
            parts = line.split()
            if not parts or parts[0] != "cpu" or len(parts) < 8:
                return None
            values = [float(v) for v in parts[1:8]]
            idle = values[3] + (float(parts[8]) if len(parts) > 8 else 0.0)  # idle + iowait
            total = sum(values)
            return total, total - idle
        except (OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _read_windows() -> tuple[float, float] | None:
        """Windows：ctypes 调 GetSystemTimes（idle/kernel/user FILETIME 各 100ns）"""
        try:
            import ctypes
            from ctypes import wintypes

            class _FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

            idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
            ok = ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            )
            if not ok:
                return None

            def _to_seconds(ft: _FILETIME) -> float:
                return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 10_000_000.0

            idle_s, kernel_s, user_s = _to_seconds(idle), _to_seconds(kernel), _to_seconds(user)
            total = kernel_s + user_s
            return total, total - idle_s
        except Exception:
            return None

    @staticmethod
    def _read_psutil() -> tuple[float, float] | None:
        """其他平台：探测到 psutil 则用 cpu_percent（interval=0 瞬时），否则 None"""
        try:
            import psutil  # type: ignore[import-not-found]
        except ImportError:
            return None
        try:
            percent = psutil.cpu_percent(interval=0.05)
            return (100.0, percent) if percent is not None else None
        except Exception:
            return None


class RuntimeSampler:
    """运行时采样器：滑动窗口 QPS/并发/CPU/延迟/错误率（§5）"""

    def __init__(
        self,
        config: CapacityConfig,
        counter_name: str = _COUNTER_REQUESTS,
        in_flight_name: str = _GAUGE_IN_FLIGHT,
        duration_name: str = _HISTOGRAM_DURATION,
    ) -> None:
        """初始化采样器。

        :param config: 容量评估配置（sample_window / sample_interval 决定窗口容量）
        :param counter_name: QPS 差分用 Counter 指标名（默认框架 http_requests_total；
            测试可注入独立指标名避免全局注册表冲突）
        :param in_flight_name: 并发用 Gauge 指标名（默认框架 http_requests_in_flight）
        :param duration_name: 分位数用 Histogram 指标名（默认框架 http_request_duration_seconds）
        """
        window_seconds = max(int(config.sample_window), 1)
        interval_seconds = max(float(config.sample_interval), 0.1)
        maxlen = max(int(window_seconds / interval_seconds), 1)
        self._samples: deque[RuntimeSnapshot] = deque(maxlen=maxlen)
        self._lock = Lock()
        self._prev_counter: float | None = None
        self._prev_ts: float | None = None
        self._cpu = CpuSampler()
        self._config = config
        self._counter_name = counter_name
        self._in_flight_name = in_flight_name
        self._duration_name = duration_name

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def sample(self) -> RuntimeSnapshot:
        """执行一次采样并写入窗口，返回本次快照。

        线程安全（asyncio 任务与 /capacity 即时补采可能并发调用）；
        QPS 需两次采样差分，首次采样 QPS 为 None（样本窗口仍计入，供后续差分）。
        """
        now = time.perf_counter()
        metrics = self._read_prometheus()
        qps = self._diff_qps(metrics["requests_total"], now)
        snapshot = RuntimeSnapshot(
            current_qps=qps,
            current_concurrency=metrics["in_flight"],
            current_cpu_percent=self._cpu.sample(),
            error_ratio=metrics["error_ratio"],
            latency_p50=metrics["latency_p50"],
            latency_p95=metrics["latency_p95"],
        )
        with self._lock:
            self._samples.append(snapshot)
            # 单次采样快照的 sample_count = 窗口当前样本数（与 snapshot() 汇总口径一致）
            snapshot = RuntimeSnapshot(
                current_qps=snapshot.current_qps,
                current_concurrency=snapshot.current_concurrency,
                current_cpu_percent=snapshot.current_cpu_percent,
                error_ratio=snapshot.error_ratio,
                latency_p50=snapshot.latency_p50,
                latency_p95=snapshot.latency_p95,
                sample_count=len(self._samples),
            )
        return snapshot

    def snapshot(self) -> RuntimeSnapshot:
        """返回窗口汇总快照（最近样本当前值 + 窗口均值/峰值 + 样本数）。

        窗口为空时返回空快照（sample_count=0，上层标注「数据不足」）。
        """
        with self._lock:
            samples = list(self._samples)
        if not samples:
            return RuntimeSnapshot()
        latest = samples[-1]
        return RuntimeSnapshot(
            current_qps=latest.current_qps,
            current_concurrency=latest.current_concurrency,
            current_cpu_percent=latest.current_cpu_percent,
            qps_mean=self._mean([s.current_qps for s in samples]),
            qps_peak=self._peak([s.current_qps for s in samples]),
            concurrency_mean=self._mean([s.current_concurrency for s in samples]),
            concurrency_peak=self._peak([s.current_concurrency for s in samples]),
            cpu_mean=self._mean([s.current_cpu_percent for s in samples]),
            cpu_peak=self._peak([s.current_cpu_percent for s in samples]),
            error_ratio=latest.error_ratio,
            latency_p50=latest.latency_p50,
            latency_p95=latest.latency_p95,
            sample_count=len(samples),
        )

    # ------------------------------------------------------------------
    # 内部：指标直读与计算
    # ------------------------------------------------------------------

    def _read_prometheus(self) -> dict[str, Any]:
        """从 prometheus 注册表直读当前指标值（聚合全部标签）。

        :return: requests_total（Counter 总和）/ in_flight（Gauge 总和）/
                 error_ratio（5xx 占比，无请求时 None）/ latency_p50/p95（秒，无样本时 None）
        """
        requests_total: float = 0.0
        errors_total: float = 0.0
        in_flight: float = 0.0
        buckets: list[tuple[float, float]] = []
        try:
            for metric_family in REGISTRY.collect():
                for sample in metric_family.samples:
                    name = sample.name
                    if name == self._counter_name:
                        requests_total += float(sample.value)
                        status_class = str(sample.labels.get("status_class", ""))
                        if status_class in ("5xx", "error"):
                            errors_total += float(sample.value)
                    elif name == self._in_flight_name:
                        in_flight += float(sample.value)
                    elif name == f"{self._duration_name}_bucket":
                        le = sample.labels.get("le")
                        if le is not None:
                            try:
                                buckets.append((float(le), float(sample.value)))
                            except ValueError:
                                continue
                    elif name == f"{self._duration_name}_count":
                        buckets.append((float("inf"), float(sample.value)))
        except Exception:
            return {
                "requests_total": requests_total,
                "in_flight": in_flight,
                "error_ratio": None,
                "latency_p50": None,
                "latency_p95": None,
            }

        error_ratio = None
        if requests_total > 0:
            error_ratio = round(errors_total / requests_total, 6)
        p50 = histogram_quantile(sorted(buckets), 0.5) if buckets else None
        p95 = histogram_quantile(sorted(buckets), 0.95) if buckets else None
        return {
            "requests_total": requests_total,
            "in_flight": in_flight,
            "error_ratio": error_ratio,
            "latency_p50": p50,
            "latency_p95": p95,
        }

    def _diff_qps(self, current_total: float, now: float) -> float | None:
        """QPS 差分：与上一次采样 Counter 差值 ÷ 真实时间戳差值（§6 快照差分语义）。

        首次采样（无基线）或时间差过小返回 None；时间差用 time.perf_counter() 实际差值
        （单调且高精度，规避 asyncio 调度抖动与 Windows monotonic 低精度导致的采样周期漂移）。
        """
        if self._prev_counter is None or self._prev_ts is None:
            self._prev_counter, self._prev_ts = current_total, now
            return None
        delta_time = now - self._prev_ts
        delta_count = current_total - self._prev_counter
        self._prev_counter, self._prev_ts = current_total, now
        if delta_time <= 0 or delta_count < 0:
            return None
        return round(delta_count / delta_time, 2)

    @staticmethod
    def _mean(values: list[float | None]) -> float | None:
        """非空值均值；全空返回 None"""
        nums = [v for v in values if v is not None]
        return round(sum(nums) / len(nums), 2) if nums else None

    @staticmethod
    def _peak(values: list[float | None]) -> float | None:
        """非空值峰值；全空返回 None"""
        nums = [v for v in values if v is not None]
        return round(max(nums), 2) if nums else None
