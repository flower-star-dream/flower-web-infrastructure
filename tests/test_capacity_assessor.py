"""
容量评估编排器 / 端点 / CLI / 装配集成测试

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 验证 CapacityAssessor（静态+运行时+集群组合、利用率、建议生成、Gauge 刷新、
              采样任务生命周期）、/capacity 端点（JSON/HTML 内容协商、403 守卫）、
              CLI（静态估算输出、退出码 0/2）、Application 装配（app.capacity.enabled
              开关、app.state.capacity、AuthMiddleware 白名单集成）。
"""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from web_infra import Application, create_app
from web_infra.capabilities.capacity.assessor import CapacityAssessor
from web_infra.capabilities.capacity.capacity_config import CapacityConfig
from web_infra.capabilities.capacity.capacity_endpoint import register_capacity_endpoints
from web_infra.capabilities.capacity.report import CapacityReport
from web_infra.infra.web import AuthMiddleware


# ------------------------------------------------------------------
# CapacityAssessor 单元
# ------------------------------------------------------------------

def _assessor(settings=None, **cfg_kwargs) -> CapacityAssessor:
    """构造评估器（静态估算为主，运行时/集群默认不拉取）"""
    application = Application(settings or {"app.name": "test"})
    config = CapacityConfig(enabled=True, cpu_cores=4, assumed_avg_latency_ms=200, **cfg_kwargs)
    return CapacityAssessor(application.settings, config)


@pytest.mark.asyncio
async def test_assess_static_fields():
    """assess：静态区（理论 QPS/安全水位/瓶颈）正确"""
    assessor = _assessor(
        {
            "app": {
                "db": {"type": "mysql", "mysql": {"pool_size": 10}},
                "cache": {"type": "redis", "redis": {"max_connections": 20}},
            }
        }
    )
    report = await assessor.assess(include_cluster=False)
    assert report.static.concurrency_limit == 10
    assert report.static.theoretical_max_qps == 50.0  # 10 / 0.2
    assert report.static.safe_qps == 35.0
    assert report.runtime is not None  # 窗口为空即时补采一次
    assert report.cluster is None  # include_cluster=False


@pytest.mark.asyncio
async def test_assess_utilization_and_suggestions():
    """assess：利用率 + 瓶颈建议"""
    assessor = _assessor(
        {
            "app": {
                "db": {"type": "mysql", "mysql": {"pool_size": 10}},
                "cache": {"type": "redis", "redis": {"max_connections": 20}},
            }
        }
    )
    report = await assessor.assess(include_cluster=False)
    assert any("瓶颈" in s for s in report.suggestions)


def test_assess_static_only_no_runtime():
    """assess_static_only：CLI 场景，运行时区为 None"""
    assessor = _assessor()
    report = assessor.assess_static_only()
    assert report.runtime is None
    assert report.static.theoretical_max_qps is not None


@pytest.mark.asyncio
async def test_sampler_start_stop_idempotent():
    """采样任务启停幂等：多次 start/stop 不抛错"""
    assessor = _assessor()
    await assessor.start()
    await assessor.start()  # 幂等：已运行不再新建
    await assessor.stop()
    await assessor.stop()  # 幂等：已停止不抛错


# ------------------------------------------------------------------
# /capacity 端点
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_capacity_endpoint_json():
    """/capacity JSON：默认内容协商返回 JSON"""
    app = FastAPI()
    assessor = _assessor()
    register_capacity_endpoints(app, assessor, service_name="test")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/capacity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["static"]["theoretical_max_qps"] is not None
    assert "generated_at" in data


@pytest.mark.asyncio
async def test_capacity_endpoint_html():
    """/capacity HTML：浏览器 Accept 返回 HTML 页面"""
    app = FastAPI()
    assessor = _assessor()
    register_capacity_endpoints(app, assessor, service_name="test")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/capacity", headers={"Accept": "text/html,application/xhtml+xml"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "并发访问能力评估" in resp.text


@pytest.mark.asyncio
async def test_capacity_endpoint_guard_denied():
    """守卫拒绝：access_guard 返回 False 时 403（E4-SYS-004）"""
    app = FastAPI()
    assessor = _assessor()
    register_capacity_endpoints(app, assessor, service_name="test", access_guard=lambda request: False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/capacity")
    assert resp.status_code == 403
    assert resp.json()["code"] == "E4-SYS-004"


@pytest.mark.asyncio
async def test_capacity_endpoint_guard_allowed():
    """守卫放行：access_guard 返回 True 时正常 200"""
    app = FastAPI()
    assessor = _assessor()
    register_capacity_endpoints(app, assessor, service_name="test", access_guard=lambda request: True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/capacity")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_capacity_endpoint_guard_instance_denied():
    """/capacity 集成：注入守卫实例（DiagnosticAccessGuard 而非 lambda），生产环境
    不可信来源 403（回归：实例无 __call__ 时端点内 access_guard(request) 抛 500）"""
    from web_infra.infra.web import DiagnosticAccessGuard

    app = FastAPI()
    assessor = _assessor()
    guard = DiagnosticAccessGuard(is_production=lambda: True)
    register_capacity_endpoints(app, assessor, service_name="test", access_guard=guard)
    # client 指定公网 IP：ASGITransport 默认回环会命中白名单放行，无法覆盖拒绝路径
    transport = httpx.ASGITransport(app=app, client=("8.8.8.8", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/capacity")
    assert resp.status_code == 403
    assert resp.json()["code"] == "E4-SYS-004"


# ------------------------------------------------------------------
# Application 装配
# ------------------------------------------------------------------

def test_app_capacity_disabled_by_default():
    """默认关闭：不注册 /capacity、app.state 无 capacity、不启动采样"""
    app = create_app({"app.name": "test"})
    paths = {route.path for route in app.routes}
    assert "/capacity" not in paths
    assert not hasattr(app.state, "capacity")


def test_app_capacity_enabled():
    """app.capacity.enabled=true：注册 /capacity + app.state.capacity"""
    app = create_app({"app.name": "test", "app.capacity.enabled": True})
    paths = {route.path for route in app.routes}
    assert "/capacity" in paths
    assert hasattr(app.state, "capacity")


def test_app_capacity_auth_whitelist_integration():
    """AuthMiddleware 集成：启用 auth 后 /capacity 因白名单匿名放行（404 而非 401）"""
    app = FastAPI()
    app.add_middleware(AuthMiddleware)  # 默认白名单已含 /capacity（阶段 0）
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")

    async def _get():
        return await client.get("/capacity")

    resp = asyncio.run(_get())
    assert resp.status_code == 404  # 白名单放行进入路由（未注册则 404 而非 401）


def test_app_capacity_metrics_gauges_registered():
    """Gauge 注册：启用后 capacity_ 指标可被 /metrics 输出"""
    app = create_app({"app.name": "test", "app.capacity.enabled": True})
    from prometheus_client import REGISTRY

    names = set()
    for collector in REGISTRY.collect():
        for sample in collector.samples:
            names.add(sample.name)
    assert "capacity_theoretical_max_qps" in names
    assert "capacity_safe_qps" in names


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def test_cli_static_report_json(monkeypatch, capsys):
    """CLI --json：静态估算 JSON 输出（无运行进程）"""
    from web_infra.capabilities.capacity import cli

    settings = Application({"app.name": "t"}).settings
    monkeypatch.setattr(cli.Settings, "instance", lambda: settings)
    exit_code = cli.main(["--json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    data = json.loads(captured.out)
    assert data["static"]["theoretical_max_qps"] is not None
    assert data["runtime"] is None  # CLI 不做运行时推断


def test_cli_all_unreachable_exit_2(monkeypatch, capsys):
    """CLI --remote 全部不可达：退出码 2 + stderr 提示"""
    from web_infra.capabilities.capacity import cli

    settings = Application(
        {"app.name": "t", "app.capacity.remote_targets": ["http://x:8001/metrics"]}
    ).settings
    monkeypatch.setattr(cli.Settings, "instance", lambda: settings)
    # 注入全失败的探针（避免真实网络）
    monkeypatch.setattr(cli, "CapacityAssessor", _FailingAssessor)
    exit_code = cli.main(["--remote"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "全部不可达" in captured.err


class _FailingAssessor:
    """CLI 测试替身：静态估算正常 + 集群全部不可达（匹配 CLI 静态+集群流程）"""

    def __init__(self, settings, config) -> None:
        from web_infra.capabilities.capacity.static_estimator import StaticEstimator

        self._estimator = StaticEstimator(settings, config)
        self._config = config
        self._probe = _FailingProbe()

    def assess_static_only(self) -> CapacityReport:
        from web_infra.capabilities.capacity.report import CapacityReport

        static = self._estimator.estimate()
        return CapacityReport(static=static, runtime=None, cluster=None)


class _FailingProbe:
    """远程探针替身：evaluate 恒返回全不可达集群"""

    async def evaluate(self, targets):
        from web_infra.capabilities.capacity.report import ClusterSnapshot, InstanceSnapshot

        return ClusterSnapshot(
            instances=tuple(
                InstanceSnapshot(url=url, status="unreachable", error="连接失败") for url in targets
            ),
            total_qps=None,
            instance_count=len(targets),
            unreachable_count=len(targets),
        )
