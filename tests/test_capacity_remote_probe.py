"""
容量评估远程探针单元测试

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 验证 RemoteProbe（设计文档 §6/§6.1/§6.2）：httpx.MockTransport 拉取 /metrics、
              快照差分（diff_interval=0）/ 独立差分（>0）、单实例失败隔离（失败只标记不影响
              其他实例）、超时/HTTP 非 200/响应体超限/解析失败分类、全部不可达判定
              （CLI 退出码 2 依据）、并发拉取不抛错。
"""
import asyncio

import httpx
import pytest

from web_infra.capabilities.capacity.capacity_config import RemoteProbeConfig
from web_infra.capabilities.capacity.remote_probe import RemoteProbe

pytestmark = pytest.mark.asyncio  # 全部用例为异步（直接调用探针 async 方法）

_OPENMETRICS = """# HELP http_requests_total HTTP 请求总数
# TYPE http_requests_total counter
http_requests_total{method="GET",path="/a",status_class="200"} 100
http_requests_total{method="GET",path="/b",status_class="5xx"} 5
"""


def _probe(config: RemoteProbeConfig | None = None, transport=None) -> RemoteProbe:
    """构造探针（默认快照差分模式；测试可注入 MockTransport）"""
    return RemoteProbe(config or RemoteProbeConfig(), transport=transport)


async def test_snapshot_diff_first_call_no_qps():
    """快照差分：首次拉取 ok 但 qps=None（数据不足，下轮差分）"""
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=_OPENMETRICS))
    probe = _probe(transport=transport)
    snapshot = await probe.evaluate(("http://svc:8001/metrics",))
    assert snapshot.instance_count == 1
    assert snapshot.unreachable_count == 0
    assert snapshot.instances[0].status == "ok"
    assert snapshot.instances[0].qps is None


async def test_snapshot_diff_second_call_qps():
    """快照差分：第二次拉取按真实时间戳差分出 QPS"""
    counter_values = iter([100, 200])

    def _handler(request: httpx.Request) -> httpx.Response:
        value = next(counter_values)
        text = f'http_requests_total{{method="GET",path="/a",status_class="200"}} {value}\n'
        return httpx.Response(200, text=text)

    probe = _probe(transport=httpx.MockTransport(_handler))
    await probe.evaluate(("http://svc:8001/metrics",))  # 首次：建基线
    await asyncio.sleep(0.01)  # 保证差分时间窗 > 0（monotonic 时钟精度）
    snapshot = await probe.evaluate(("http://svc:8001/metrics",))  # 第二次：差分
    assert snapshot.instances[0].qps is not None


async def test_independent_diff():
    """独立差分（diff_interval>0）：一次评估内连续拉两次"""
    counter_values = iter([50, 100])

    def _handler(request: httpx.Request) -> httpx.Response:
        value = next(counter_values)
        text = f'http_requests_total{{method="GET",path="/a",status_class="200"}} {value}\n'
        return httpx.Response(200, text=text)

    probe = _probe(RemoteProbeConfig(diff_interval=0.01), transport=httpx.MockTransport(_handler))
    snapshot = await probe.evaluate(("http://svc:8001/metrics",))
    assert snapshot.instances[0].status == "ok"
    assert snapshot.instances[0].qps is not None


async def test_partial_unreachable_isolated():
    """单实例失败隔离：一个不可达不影响其他实例评估"""
    def _handler(request: httpx.Request) -> httpx.Response:
        if "down" in request.url.host:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, text=_OPENMETRICS)

    probe = _probe(transport=httpx.MockTransport(_handler))
    snapshot = await probe.evaluate(("http://up:8001/metrics", "http://down:8002/metrics"))
    assert snapshot.instance_count == 2
    assert snapshot.unreachable_count == 1
    statuses = {i.url: i.status for i in snapshot.instances}
    assert statuses["http://up:8001/metrics"] == "ok"
    assert statuses["http://down:8002/metrics"] == "unreachable"
    assert snapshot.all_unreachable is False


async def test_all_unreachable():
    """全部不可达：all_unreachable=True（CLI 退出码 2 依据）"""
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    probe = _probe(transport=httpx.MockTransport(_handler))
    snapshot = await probe.evaluate(("http://a:8001/metrics", "http://b:8002/metrics"))
    assert snapshot.all_unreachable is True
    assert snapshot.total_qps is None


async def test_http_non_200_classified():
    """HTTP 非 200：标记不可达并给出可读原因（端点异常）"""
    probe = _probe(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    snapshot = await probe.evaluate(("http://svc:8001/metrics",))
    instance = snapshot.instances[0]
    assert instance.status == "unreachable"
    assert "503" in instance.error


async def test_parse_failure_classified():
    """解析失败：响应不是合法 Prometheus 文本 → 标记不可达并说明"""
    probe = _probe(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="not-a-metric")))
    snapshot = await probe.evaluate(("http://svc:8001/metrics",))
    instance = snapshot.instances[0]
    assert instance.status == "unreachable"
    assert "Prometheus" in instance.error


async def test_response_size_limit():
    """响应体超限（max_response_bytes）：按解析失败处理"""
    probe = _probe(
        RemoteProbeConfig(max_response_bytes=16),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=_OPENMETRICS)),
    )
    snapshot = await probe.evaluate(("http://svc:8001/metrics",))
    assert snapshot.instances[0].status == "unreachable"
    assert "超限" in snapshot.instances[0].error


async def test_timeout_total_cap():
    """总耗时上限：asyncio.wait_for 生效（长时间挂起请求被中断为不可达）"""
    async def _slow_handler(request: httpx.Request) -> httpx.Response:
        import asyncio

        await asyncio.sleep(5.0)  # 超过 timeout=0.1
        return httpx.Response(200, text=_OPENMETRICS)

    probe = _probe(RemoteProbeConfig(timeout=0.1), transport=httpx.MockTransport(_slow_handler))
    snapshot = await probe.evaluate(("http://svc:8001/metrics",))
    assert snapshot.instances[0].status == "unreachable"


async def test_empty_targets():
    """空 targets：返回空集群快照（不拉取）"""
    probe = _probe()
    snapshot = await probe.evaluate(())
    assert snapshot.instance_count == 0
    assert snapshot.total_qps is None
