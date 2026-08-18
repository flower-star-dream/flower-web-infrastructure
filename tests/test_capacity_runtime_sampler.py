"""
容量评估运行时采样器单元测试

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 验证 RuntimeSampler：prometheus 指标直读（QPS 差分/in_flight/分位数近似/错误率）、
              滑动窗口均值/峰值汇总、窗口为空降级、CPU 采样跨平台降级（Linux/Windows 真实
              采样 + 不可用返回 None）、线程安全（并发采样不丢样本）。
              使用独立指标名（cap_test_ 前缀）注入采样器，避免与框架全局注册表同名冲突。
"""
import sys
import threading
import time

import pytest
from prometheus_client import Counter, Gauge, Histogram

from web_infra.capabilities.capacity.capacity_config import CapacityConfig
from web_infra.capabilities.capacity.runtime_sampler import CpuSampler, RuntimeSampler

# 独立指标名（与框架 http_* 隔离，避免全局注册表 DuplicateTimeseries）
_COUNTER = "cap_test_http_requests_total"
_IN_FLIGHT = "cap_test_http_requests_in_flight"
_DURATION = "cap_test_http_request_duration_seconds"


@pytest.fixture(autouse=True)
def _clean_cap_metrics():
    """清理本模块注册的 cap_test_ 指标（prometheus 注册表全局共享，跨用例需隔离）"""
    from prometheus_client import REGISTRY

    collectors = [
        c
        for c in list(REGISTRY._collector_to_names.keys())
        if any(name.startswith("cap_test_") for name in REGISTRY._collector_to_names[c])
    ]
    for c in collectors:
        REGISTRY.unregister(c)
    yield


def _sampler(**kwargs) -> RuntimeSampler:
    """构造注入独立指标名的采样器"""
    return RuntimeSampler(CapacityConfig(**kwargs), counter_name=_COUNTER, in_flight_name=_IN_FLIGHT, duration_name=_DURATION)


def _register_http_metrics() -> tuple[Counter, Gauge, Histogram]:
    """注册模拟 http RED 指标（独立指标名）"""
    counter = Counter(_COUNTER, "t", ["method", "path", "status_class"])
    gauge = Gauge(_IN_FLIGHT, "t", ["service"])
    hist = Histogram(_DURATION, "t", ["service", "method", "path"])
    return counter, gauge, hist


def test_snapshot_empty_window():
    """窗口为空：snapshot 返回空快照（sample_count=0，数据不足降级）"""
    sampler = _sampler()
    snap = sampler.snapshot()
    assert snap.sample_count == 0
    assert snap.current_qps is None


def test_snapshot_after_samples():
    """多次采样后窗口汇总：当前值 + 均值/峰值"""
    counter, gauge, hist = _register_http_metrics()
    sampler = _sampler(sample_window=60, sample_interval=5)
    gauge.labels("svc").set(7)
    hist.labels("svc", "GET", "/a").observe(0.1)
    counter.labels("GET", "/a", "200").inc(10)
    sampler.sample()  # 首次：QPS=None（需差分基线）
    time.sleep(0.01)  # 保证差分时间窗 > 0（monotonic 时钟精度）
    counter.labels("GET", "/a", "200").inc(10)
    sampler.sample()  # 第二次：QPS 差分

    snap = sampler.snapshot()
    assert snap.sample_count == 2
    assert snap.current_concurrency == 7.0
    assert snap.current_qps is not None and snap.current_qps > 0
    # 直方图分位数（0.1s 采样一次 → P50/P95 ≈ 0.1）
    assert snap.latency_p50 is not None and 0.05 <= snap.latency_p50 <= 0.1
    assert snap.latency_p95 is not None and 0.05 <= snap.latency_p95 <= 0.1


def test_error_ratio():
    """错误率：5xx/error 请求占比"""
    counter, _, _ = _register_http_metrics()
    counter.labels("GET", "/a", "200").inc(80)
    counter.labels("GET", "/a", "5xx").inc(20)
    sampler = _sampler()
    snap = sampler.sample()
    assert snap.error_ratio == 0.2


def test_no_requests_error_ratio_none():
    """无请求：错误率 None（不除零）"""
    sampler = _sampler()
    snap = sampler.sample()
    assert snap.error_ratio is None


def test_qps_diff_requires_two_samples():
    """QPS 差分：首次采样 None，第二次有值"""
    counter, _, _ = _register_http_metrics()
    sampler = _sampler()
    counter.labels("GET", "/a", "200").inc(5)
    first = sampler.sample()
    assert first.current_qps is None
    time.sleep(0.01)  # 保证差分时间窗 > 0
    counter.labels("GET", "/a", "200").inc(5)
    second = sampler.sample()
    assert second.current_qps is not None


def test_window_rolling():
    """滑动窗口滚动：超过容量后旧样本被挤出"""
    counter, _, _ = _register_http_metrics()
    sampler = _sampler(sample_window=5, sample_interval=5)  # maxlen=1
    counter.labels("GET", "/a", "200").inc(1)
    sampler.sample()
    counter.labels("GET", "/a", "200").inc(1)
    sampler.sample()
    snap = sampler.snapshot()
    assert snap.sample_count == 1  # 仅保留最近样本


def test_concurrent_sample_thread_safe():
    """并发采样线程安全：多线程采样不抛错且窗口样本完整"""
    counter, _, _ = _register_http_metrics()
    sampler = _sampler(sample_window=60, sample_interval=0.1)  # maxlen=600

    def _do_sample():
        for _ in range(20):
            counter.labels("GET", "/a", "200").inc(1)
            sampler.sample()

    threads = [threading.Thread(target=_do_sample) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    snap = sampler.snapshot()
    assert snap.sample_count == 80


def test_cpu_sampler_platform():
    """CPU 采样：Windows/Linux 可采样或返回 None（不抛错），其他平台降级 None"""
    sampler = CpuSampler()
    if sys.platform.startswith("linux") or sys.platform == "win32":
        first = sampler.sample()
        second = sampler.sample()
        assert second is None or 0 <= second <= 100
    else:
        # 其他平台无 psutil 时返回 None（优雅降级）
        assert sampler.sample() is None


def test_snapshot_does_not_block_on_empty():
    """窗口为空时 snapshot 返回空快照（非阻塞，sample_count=0）"""
    sampler = _sampler()
    start = time.monotonic()
    snap = sampler.snapshot()
    assert time.monotonic() - start < 1.0
    assert snap.sample_count == 0


def test_custom_metric_names_isolated():
    """独立指标名注入：未注册对应指标时窗口仍可采样（0 值不抛错）"""
    sampler = _sampler()
    snap = sampler.sample()
    assert snap.current_concurrency == 0.0
    assert snap.sample_count == 1
