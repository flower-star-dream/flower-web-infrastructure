"""
韧性设计单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证重试、熔断（含 fallback 降级）、限流行为（规范 §7）与 FeignClient 熔断集成（S7-4）。
"""
import asyncio

import pytest

from web_infra.resilience import (
    RetryConfig,
    retry,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    RateLimitConfig,
    TokenBucketRateLimiter,
)


def test_retry_transient_error_recovers():
    """瞬时错误自动重试直至成功"""
    calls = []

    @retry(RetryConfig(max_retries=2, base_delay=0.0))
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("临时网络错误")
        return "ok"

    assert flaky() == "ok"
    assert len(calls) == 3


def test_retry_non_transient_error_no_retry():
    """非瞬时错误不重试，直接抛出"""
    calls = []

    @retry(RetryConfig(max_retries=2, base_delay=0.0))
    def failing():
        calls.append(1)
        raise ValueError("业务错误")

    with pytest.raises(ValueError):
        failing()
    assert len(calls) == 1


def test_retry_max_retries_exceeded():
    """超过最大重试次数后抛出"""
    calls = []

    @retry(RetryConfig(max_retries=2, base_delay=0.0))
    def always_fail():
        calls.append(1)
        raise ConnectionError("一直失败")

    with pytest.raises(ConnectionError):
        always_fail()
    assert len(calls) == 3  # 首次 + 2 次重试


def test_circuit_breaker_opens_after_failures():
    """错误率超阈值后熔断开启"""
    cb = CircuitBreaker("test", CircuitBreakerConfig(minimum_number_of_calls=5))

    def ok():
        return "ok"

    def fail():
        raise RuntimeError("fail")

    # 先失败足够多次触发熔断
    for _ in range(5):
        with pytest.raises(RuntimeError):
            cb.execute(fail)

    with pytest.raises(CircuitOpenError):
        cb.execute(ok)


def test_rate_limiter_token_bucket():
    """令牌桶限流：耗尽令牌后拒绝"""
    # qps=0 表示无补充，仅初始 burst 个令牌，保证测试确定性
    limiter = TokenBucketRateLimiter("test", RateLimitConfig(qps=0.0, burst=2.0))
    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is False


def test_rate_limiter_retry_after_seconds():
    """retry_after_seconds：令牌足够返回 0，耗尽后按 qps 估算等待秒数"""
    limiter = TokenBucketRateLimiter("test", RateLimitConfig(qps=2.0, burst=2.0))
    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is True
    assert limiter.retry_after_seconds() > 0  # 桶空，需等待补充 1 个令牌（0.5s）

    fresh = TokenBucketRateLimiter("test", RateLimitConfig(qps=0.0, burst=1.0))
    assert fresh.retry_after_seconds() == 0.0  # 桶满，无需等待
    fresh.try_acquire()
    assert fresh.retry_after_seconds() == float("inf")  # qps=0 无法补充


# ------------------------------------------------------------------
# 整改 S7-4：熔断降级 fallback
# ------------------------------------------------------------------

def test_circuit_breaker_fallback_on_exception():
    """调用异常时返回 fallback 兜底值（异常不裸抛）"""
    cb = CircuitBreaker("test", CircuitBreakerConfig(), fallback=lambda *a, **k: "fallback")

    def fail():
        raise RuntimeError("fail")

    assert cb.execute(fail) == "fallback"


def test_circuit_breaker_fallback_on_open():
    """熔断开启后返回 fallback 兜底值（不再抛 CircuitOpenError）"""
    cb = CircuitBreaker(
        "test",
        CircuitBreakerConfig(minimum_number_of_calls=5),
        fallback=lambda *a, **k: "fallback",
    )

    def fail():
        raise RuntimeError("fail")

    # 调用异常时降级返回 fallback，同时累计错误样本
    for _ in range(5):
        assert cb.execute(fail) == "fallback"
    # 样本达标已熔断开启
    from web_infra.resilience import CircuitBreakerState

    assert cb.state == CircuitBreakerState.OPEN
    # OPEN 状态直接降级
    assert cb.execute(lambda: "ok") == "fallback"


def test_circuit_breaker_no_fallback_keeps_open_error():
    """未配置 fallback 时熔断开启仍抛 CircuitOpenError（保持原语义）"""
    cb = CircuitBreaker("test", CircuitBreakerConfig(minimum_number_of_calls=5))

    def fail():
        raise RuntimeError("fail")

    for _ in range(5):
        with pytest.raises(RuntimeError):
            cb.execute(fail)

    with pytest.raises(CircuitOpenError):
        cb.execute(lambda: "ok")


@pytest.mark.asyncio
async def test_circuit_breaker_async_fallback():
    """异步调用异常时走同步/异步 fallback"""
    cb = CircuitBreaker("test", CircuitBreakerConfig(), fallback=lambda *a, **k: "sync-fb")

    async def fail():
        raise RuntimeError("fail")

    assert await cb.execute_async(fail) == "sync-fb"

    async def async_fb(*a, **k):
        return "async-fb"

    cb2 = CircuitBreaker("test", CircuitBreakerConfig(), fallback=async_fb)
    assert await cb2.execute_async(fail) == "async-fb"


@pytest.mark.asyncio
async def test_feign_client_circuit_breaker_fallback():
    """FeignClient 集成熔断：目标服务持续失败触发熔断开启，期间与开启后均走 fallback 返回 None"""
    from web_infra.http import FeignClient
    from web_infra.registry import InMemoryServiceRegistry, ServiceInstance
    from web_infra.resilience import CircuitBreakerState

    registry = InMemoryServiceRegistry()
    # 指向本机未监听端口（port 9 discard），保证连接失败
    await registry.register("svc", ServiceInstance(ip="127.0.0.1", port=9))

    client = FeignClient(
        registry,
        retries=1,
        retry_delay_base=0.0,
        circuit_breaker_config=CircuitBreakerConfig(minimum_number_of_calls=2),
        fallback=lambda service_name: None,
    )
    try:
        # 失败调用降级返回 None（fallback），同时累计错误样本触发熔断
        for _ in range(3):
            assert await client.request("svc", "GET", "/x") is None
        breaker = client._breakers["svc"]
        assert breaker.state == CircuitBreakerState.OPEN
        # 熔断开启后仍走 fallback，不抛异常
        assert await client.request("svc", "GET", "/x") is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_feign_client_without_circuit_breaker_unchanged():
    """未配置熔断时 FeignClient 行为不变：失败仍抛 BizException"""
    from web_infra.error import BizException
    from web_infra.http import FeignClient
    from web_infra.registry import InMemoryServiceRegistry, ServiceInstance

    registry = InMemoryServiceRegistry()
    await registry.register("svc", ServiceInstance(ip="127.0.0.1", port=9))

    client = FeignClient(registry, retries=1, retry_delay_base=0.0)
    try:
        with pytest.raises(BizException):
            await client.request("svc", "GET", "/x")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_feign_client_default_fallback():
    """FeignClient 未传 fallback 时采用框架默认兜底：统一 503 服务不可用响应（S7-4）

    业务无需为每个客户端重复实现降级；需自定义降级（如返回缓存数据）时传 fallback 参数覆盖。
    """
    from web_infra.error import CommonErrorCode
    from web_infra.http import FeignClient
    from web_infra.registry import InMemoryServiceRegistry, ServiceInstance

    registry = InMemoryServiceRegistry()
    # 指向本机未监听端口（port 9 discard），保证连接失败触发熔断降级
    await registry.register("svc", ServiceInstance(ip="127.0.0.1", port=9))

    client = FeignClient(
        registry,
        retries=1,
        retry_delay_base=0.0,
        circuit_breaker_config=CircuitBreakerConfig(minimum_number_of_calls=1),
    )
    try:
        resp = await client.request("svc", "GET", "/x")
        assert resp is not None
        assert resp.status_code == CommonErrorCode.SYS_UNAVAILABLE.http_status  # 503
        body = resp.json()
        assert body["code"] == CommonErrorCode.SYS_UNAVAILABLE.code  # E5-SYS-002
        assert "svc" in body["message"]
    finally:
        await client.close()


def test_circuit_breaker_recovers_after_half_open_success():
    """半开探测成功：熔断器恢复关闭（HALF_OPEN → CLOSED），不再永久停留在半开"""
    import time

    from web_infra.resilience import CircuitBreakerState

    cb = CircuitBreaker(
        "test",
        CircuitBreakerConfig(
            minimum_number_of_calls=3,
            wait_duration_in_open_state=0.05,
            permitted_calls_in_half_open_state=2,
        ),
    )

    def fail():
        raise RuntimeError("fail")

    def ok():
        return "ok"

    # 失败样本达标触发熔断开启
    for _ in range(3):
        with pytest.raises(RuntimeError):
            cb.execute(fail)
    assert cb.state == CircuitBreakerState.OPEN

    # 轮询等待 OPEN 到期（规避 sleep 粒度不足的时序抖动），由 execute 触发进入 HALF_OPEN
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and time.monotonic() < cb._open_until:
        time.sleep(0.005)
    # 半开探测成功 → 熔断器恢复 CLOSED
    assert cb.execute(ok) == "ok"
    assert cb.state == CircuitBreakerState.CLOSED


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_license_recovered_on_cancel():
    """半开探测调用被取消：半开许可被回收（CancelledError 不泄漏），熔断器仍可恢复"""
    import asyncio
    import time

    from web_infra.resilience import CircuitBreakerState

    cb = CircuitBreaker(
        "test",
        CircuitBreakerConfig(
            minimum_number_of_calls=3,
            wait_duration_in_open_state=0.05,
            permitted_calls_in_half_open_state=1,
        ),
    )

    async def never_finish():
        await asyncio.sleep(10)

    # 失败样本达标触发熔断开启
    for _ in range(3):
        with pytest.raises(RuntimeError):
            cb.execute(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
    assert cb.state == CircuitBreakerState.OPEN

    # 轮询等待 OPEN 到期（规避 sleep 粒度不足的时序抖动），由探测任务触发进入 HALF_OPEN
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and time.monotonic() < cb._open_until:
        time.sleep(0.005)
    # 半开探测调用被取消：CancelledError 需按失败记录回收许可（修复前许可永久泄漏）
    task = asyncio.create_task(cb.execute_async(never_finish))
    await asyncio.sleep(0.02)
    assert cb.state == CircuitBreakerState.HALF_OPEN  # 探测任务已进入半开并持有许可
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # 取消已按失败记录（半开失败重新 OPEN）；等待到期后再次探测成功应恢复 CLOSED
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and time.monotonic() < cb._open_until:
        time.sleep(0.005)
    assert cb.execute(lambda: "ok") == "ok"
    assert cb.state == CircuitBreakerState.CLOSED
