"""
容量评估静态估算器单元测试

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 验证 StaticEstimator：逐组件并发上限（§4.2）、min 瓶颈模型（§4.3）、
              Little's Law 理论 QPS、安全水位（§4.4）、限流/SLO 反推（§4.5）、
              IO/CPU 密集切换、CPU 核数配置覆盖。
"""
import pytest

from web_infra.capabilities.capacity.capacity_config import CapacityConfig
from web_infra.capabilities.capacity.static_estimator import StaticEstimator
from web_infra.infra.config.settings import Settings


def _settings(**overrides) -> Settings:
    """构造带默认 db/cache/mongo/rate_limit 配置的 Settings（测试确定性，dict 深合并）"""
    from web_infra import Application

    base = {
        "app": {
            "db": {"type": "mysql", "mysql": {"pool_size": 10}},
            "cache": {"type": "redis", "redis": {"max_connections": 20}},
            "mongo": {"enabled": True, "max_pool_size": 30},
            "web": {"middlewares": {"rate_limit": {"enabled": True, "qps": 500}}},
        }
    }
    merged = _deep_merge(base, dict(overrides))
    # dict 入参叠加默认源（与 Application._resolve_settings 一致，未提供的键回落 yml 默认值）
    return Application(merged).settings


def _deep_merge(base: dict, override: dict) -> dict:
    """递归深合并 dict（override 覆盖 base 的叶子值，保留未覆盖的键）"""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def test_component_capacities_and_bottleneck():
    """逐组件并发上限 + min 瓶颈（mysql=10 最小 → 瓶颈 mysql）"""
    est = StaticEstimator(_settings(), CapacityConfig(cpu_cores=4))
    result = est.estimate()
    names = {c.name: c.concurrency_limit for c in result.components}
    assert names["mysql"] == 10
    assert names["redis"] == 20
    assert names["mongo"] == 30
    assert names["cpu"] == 4 * 25  # IO 密集：核数 × 系数
    assert result.concurrency_limit == 10
    assert result.bottleneck == "mysql"


def test_little_law_qps_and_safe_watermark():
    """Little's Law：并发 10 ÷ 0.2s = 50 QPS；安全水位 50 × 0.7 = 35"""
    est = StaticEstimator(_settings(), CapacityConfig(cpu_cores=4, assumed_avg_latency_ms=200))
    result = est.estimate()
    assert result.concurrency_limit == 10
    assert result.theoretical_max_qps == 50.0
    assert result.safe_qps == 35.0


def test_cpu_intensive_workload():
    """CPU 密集：cpu 并发 = 核数（不再乘系数）"""
    est = StaticEstimator(
        _settings(), CapacityConfig(cpu_cores=4, workload_type="cpu_intensive", io_concurrency_factor=25)
    )
    result = est.estimate()
    cpu = next(c for c in result.components if c.name == "cpu")
    assert cpu.concurrency_limit == 4


def test_cpu_cores_config_override():
    """CPU 核数配置覆盖探测值（不依赖机器核数，测试确定）"""
    est = StaticEstimator(_settings(), CapacityConfig(cpu_cores=8))
    result = est.estimate()
    assert result.cpu_cores == 8
    cpu = next(c for c in result.components if c.name == "cpu")
    assert cpu.concurrency_limit == 8 * 25


def test_rate_limit_reverse_inference():
    """限流反推：限流 qps=500 < 理论 QPS → effective_max_qps 受限并标记"""
    # 理论 QPS = 10 / 0.2 = 50 < 500：不受限
    est = StaticEstimator(_settings(), CapacityConfig(cpu_cores=4, assumed_avg_latency_ms=200))
    result = est.estimate()
    assert result.rate_limit_qps == 500
    assert result.effective_max_qps == 50.0
    assert result.rate_limit_limited is False

    # 调大各维度并发使理论 QPS > 500 → 受限
    # （mysql/redis/mongo=1000、web/cpu=4×200=800 → 瓶颈 800 → 理论 QPS 4000 > 500）
    settings = _settings(
        **{
            "app": {
                "db": {"mysql": {"pool_size": 1000}},
                "cache": {"redis": {"max_connections": 1000}},
                "mongo": {"max_pool_size": 1000},
                "web": {"middlewares": {"rate_limit": {"qps": 500}}},
            }
        }
    )
    est2 = StaticEstimator(
        settings, CapacityConfig(cpu_cores=4, io_concurrency_factor=200, assumed_avg_latency_ms=200)
    )
    result2 = est2.estimate()
    assert result2.effective_max_qps == 500.0
    assert result2.rate_limit_limited is True


def test_rate_limit_disabled_no_inference():
    """未启用限流中间件：rate_limit_qps=None，不反推受限"""
    settings = _settings(**{"app": {"web": {"middlewares": {"rate_limit": {"enabled": False}}}}})
    est = StaticEstimator(settings, CapacityConfig(cpu_cores=4))
    result = est.estimate()
    assert result.rate_limit_qps is None
    assert result.rate_limit_limited is False


def test_slo_allowed_error_ratio():
    """SLO 反推：默认目标可用性 0.99 → 允许错误率 0.01"""
    est = StaticEstimator(_settings(), CapacityConfig())
    result = est.estimate()
    assert result.allowed_error_ratio == 0.01


def test_no_pool_config_skips_component():
    """未装配组件（db=sqlite / cache=memory / mongo 关闭）不计入瓶颈，仅剩 web+cpu 维度"""
    from web_infra import Application

    settings = Application(
        {
            "app.name": "x",
            "app.db.type": "sqlite",
            "app.cache.type": "memory",
            "app.mongo.enabled": False,
        }
    ).settings
    est = StaticEstimator(settings, CapacityConfig(cpu_cores=2))
    result = est.estimate()
    names = [c.name for c in result.components]
    assert names == ["web", "cpu"]
    assert result.bottleneck == "web"  # web=2×25=cpu=2×25，取先列出的维度


def test_estimate_is_immutable_dataclass():
    """估算结果不可变（frozen），且 components 为元组"""
    est = StaticEstimator(_settings(), CapacityConfig(cpu_cores=4))
    result = est.estimate()
    assert isinstance(result.components, tuple)
    with pytest.raises(Exception):
        result.concurrency_limit = 99  # type: ignore[misc]
