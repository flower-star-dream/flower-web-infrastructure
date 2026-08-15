"""
健康检查与指标端点单元测试

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 验证健康检查三端点（整改 S19-1）：GET /health/live（存活，不探测依赖）、
              GET /health/ready（组件连通性探测，DOWN 返回 503）、GET /health（兼容聚合入口），
              与 GET /metrics（Prometheus 文本），规范 §19.4 / §18.1。
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web_infra.web import register_health_endpoints


class _HealthyComponent:
    """探测为 UP 的组件"""

    async def health_check(self) -> bool:
        return True


class _DownComponent:
    """探测为 DOWN 的组件"""

    async def health_check(self) -> bool:
        return False


class _NoHealthComponent:
    """无 health_check 方法的组件（视为 UP）"""


class _RaisingComponent:
    """health_check 抛异常的组件（视为 DOWN）"""

    async def health_check(self) -> bool:
        raise RuntimeError("probe failed")


def _build_app(components: dict) -> FastAPI:
    """构建带健康端点的测试应用"""
    app = FastAPI()
    register_health_endpoints(app, components=components, service_name="test-service")
    return app


def test_health_all_up():
    """全部组件健康：返回 200 且各组件 UP"""
    client = TestClient(_build_app({"db": _HealthyComponent(), "plain": _NoHealthComponent()}))
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "UP"
    assert body["service"] == "test-service"
    assert body["components"]["db"] == "UP"
    assert body["components"]["plain"] == "UP"


def test_health_component_down_returns_503():
    """任一组件 DOWN：返回 503 且 status=DOWN"""
    client = TestClient(_build_app({"db": _DownComponent()}))
    resp = client.get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "DOWN"
    assert body["components"]["db"] == "DOWN"


def test_health_probe_exception_treated_as_down():
    """组件探测抛异常：视为 DOWN"""
    client = TestClient(_build_app({"db": _RaisingComponent()}))
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["components"]["db"] == "DOWN"


def test_health_without_components():
    """无组件时健康检查返回 200"""
    client = TestClient(_build_app({}))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "UP"


# ---- 整改 S19-1：存活/就绪分离 ----

def test_health_live_returns_up():
    """live 探针：进程存活返回 200/UP，且不包含组件状态"""
    client = TestClient(_build_app({}))
    resp = client.get("/health/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "UP"
    assert body["service"] == "test-service"
    assert "components" not in body


def test_health_live_ignores_component_down():
    """live 探针不探测依赖：组件 DOWN 时仍返回 200/UP（存活与就绪分离）"""
    client = TestClient(_build_app({"db": _DownComponent()}))
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "UP"


def test_health_ready_all_up():
    """ready 探针：全部组件健康返回 200 且各组件 UP"""
    client = TestClient(_build_app({"db": _HealthyComponent(), "plain": _NoHealthComponent()}))
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "UP"
    assert body["components"]["db"] == "UP"
    assert body["components"]["plain"] == "UP"


def test_health_ready_component_down_returns_503():
    """ready 探针探测依赖：任一组件 DOWN 返回 503（就绪失败不摘除存活）"""
    client = TestClient(_build_app({"db": _DownComponent()}))
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "DOWN"
    assert body["components"]["db"] == "DOWN"


def test_health_live_and_ready_independent():
    """同一应用：组件 DOWN 时 live 为 200/UP 而 ready 为 503（存活/就绪职责分离）"""
    client = TestClient(_build_app({"db": _RaisingComponent()}))
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503
    assert client.get("/health").status_code == 503


def test_metrics_endpoint_returns_prometheus_text():
    """/metrics 返回 Prometheus 文本格式"""
    client = TestClient(_build_app({}))
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert b"http_requests_total" in resp.content


def test_metrics_html_for_browser_accept():
    """浏览器 Accept 含 text/html：/metrics 返回 HTML 可视化页面"""
    client = TestClient(_build_app({}))
    resp = client.get("/metrics", headers={"Accept": "text/html,application/xhtml+xml"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "指标总览" in resp.text
    # 无请求数据时 HTTP RED 分组不渲染（按样本动态）；Python 运行时由抓取时刷新必有数据
    assert "HTTP RED 指标" not in resp.text
    assert "Python 运行时" in resp.text


def test_metrics_format_text_forces_plain():
    """?format=text 强制返回 Prometheus 文本（即使 Accept 为 html）"""
    client = TestClient(_build_app({}))
    resp = client.get("/metrics?format=text", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert b"http_requests_total" in resp.content


def test_metrics_format_html_forces_html():
    """?format=html 强制返回 HTML 页面（即使无浏览器 Accept）"""
    client = TestClient(_build_app({}))
    resp = client.get("/metrics?format=html")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "指标总览" in resp.text


def test_metrics_disabled_when_flag_false():
    """enable_metrics=False 时不注册 /metrics"""
    app = FastAPI()
    register_health_endpoints(app, components={}, enable_metrics=False)
    client = TestClient(app)
    assert client.get("/metrics").status_code == 404
