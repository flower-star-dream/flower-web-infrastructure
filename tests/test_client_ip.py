"""
客户端真实 IP 解析与访问日志真实 IP 集成单元测试

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 验证 IPAddressUtil 私网/保留段与可信代理判断、get_client_ip / apply_real_client_ip 真实 IP 解析与写回，
              以及日志中间件访问日志输出 uvicorn 标准格式的真实客户端 IP、关闭 uvicorn 原生访问日志。
"""
import logging
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from web_infra.infra.monitoring import metrics
from web_infra.infra.utils.ip_address_util import IPAddressUtil
from web_infra.infra.web.client_ip import apply_real_client_ip, get_client_ip
from web_infra.infra.web.logging_middleware import LoggingMiddleware, disable_uvicorn_access_log, setup_uvicorn_access_log


@pytest.fixture(autouse=True)
def _restore_uvicorn_access():
    """快照并恢复 uvicorn.access 日志器状态（handlers/propagate），避免污染同进程其他测试"""
    uvicorn_access = logging.getLogger("uvicorn.access")
    saved_handlers = list(uvicorn_access.handlers)
    saved_propagate = uvicorn_access.propagate
    yield
    uvicorn_access.handlers = saved_handlers
    uvicorn_access.propagate = saved_propagate


@pytest.fixture(autouse=True)
def _clean_red_metrics():
    """清理本文件集成测试经中间件写入的 RED 指标样本（http_requests_total 等）。

    全局 prometheus 指标跨测试累积，本文件按字母序先于 test_health 运行，
    若不清理会使 test_health 的"无请求样本不渲染 HTTP RED 分组"断言被顺序污染。
    """
    yield
    metrics.HTTP_REQUESTS_TOTAL.clear()
    metrics.HTTP_REQUEST_ERRORS_TOTAL.clear()
    metrics.HTTP_REQUEST_DURATION_SECONDS.clear()
    metrics.REQUEST_PHASE_DURATION_SECONDS.clear()
    metrics.HTTP_REQUESTS_IN_FLIGHT.clear()


# ---------------------------------------------------------------------------
# IPAddressUtil：私网/保留段与可信代理判断
# ---------------------------------------------------------------------------


def test_is_private_or_reserved():
    """私网/保留/特殊用途网段判定（容器网络、内网 NAT、回环等）"""
    assert IPAddressUtil.is_private_or_reserved("10.0.0.1")
    assert IPAddressUtil.is_private_or_reserved("172.16.0.1")
    assert IPAddressUtil.is_private_or_reserved("172.18.0.1")
    assert IPAddressUtil.is_private_or_reserved("192.168.1.1")
    assert IPAddressUtil.is_private_or_reserved("127.0.0.1")
    assert IPAddressUtil.is_private_or_reserved("::1")
    assert IPAddressUtil.is_private_or_reserved("100.64.0.1")  # CGNAT 共享地址
    assert not IPAddressUtil.is_private_or_reserved("8.8.8.8")
    assert not IPAddressUtil.is_private_or_reserved("114.114.114.114")
    # 无法解析的非法 IP 视为私网（fail-open，绝不误封）
    assert IPAddressUtil.is_private_or_reserved("not-an-ip")


def test_is_trusted_proxy():
    """默认可信代理为回环 + 私网段（容器网络内 OpenResty/APISIX 开箱即用）"""
    assert IPAddressUtil.is_trusted_proxy("127.0.0.1")
    assert IPAddressUtil.is_trusted_proxy("10.0.0.5")
    assert IPAddressUtil.is_trusted_proxy("172.18.0.1")
    assert not IPAddressUtil.is_trusted_proxy("8.8.8.8")


# ---------------------------------------------------------------------------
# get_client_ip / apply_real_client_ip：真实客户端 IP 解析与写回
# ---------------------------------------------------------------------------


def _fake_request(client_host: str | None = None, headers: dict | None = None):
    """构造最小请求替身（仅暴露 get_client_ip 依赖的 client / headers）"""
    return SimpleNamespace(
        client=SimpleNamespace(host=client_host) if client_host else None,
        headers=headers or {},
    )


def test_get_client_ip_trusted_proxy_x_real_ip():
    """可信代理透传 X-Real-IP 时优先取 X-Real-IP（去空白）"""
    req = _fake_request(client_host="10.0.0.5", headers={"x-real-ip": " 1.2.3.4 "})
    assert get_client_ip(req) == "1.2.3.4"


def test_get_client_ip_trusted_proxy_xff_last():
    """可信代理透传 X-Forwarded-For 时取最后一项（$proxy_add_x_forwarded_for 末尾为直连方真实 IP）"""
    req = _fake_request(client_host="10.0.0.5", headers={"x-forwarded-for": "6.6.6.6, 7.7.7.7, 8.8.8.8"})
    assert get_client_ip(req) == "8.8.8.8"


def test_get_client_ip_trusted_proxy_without_headers_fallback_direct():
    """可信代理但无代理头时回落直连方地址"""
    req = _fake_request(client_host="10.0.0.5")
    assert get_client_ip(req) == "10.0.0.5"


def test_get_client_ip_untrusted_ignores_headers():
    """不可信直连方忽略一切代理头（防绕过代理直连后端伪造代理头封禁任意 IP）"""
    req = _fake_request(client_host="8.8.8.8", headers={"x-real-ip": "1.2.3.4", "x-forwarded-for": "6.6.6.6"})
    assert get_client_ip(req) == "8.8.8.8"


def test_get_client_ip_no_client():
    """无法获取直连方时返回 None"""
    assert get_client_ip(_fake_request()) is None


def test_apply_real_client_ip_rewrites_scope():
    """真实 IP 写回 scope["client"]（保留原端口）"""
    scope = {"client": ("172.18.0.1", 43750)}
    apply_real_client_ip(SimpleNamespace(scope=scope), "1.2.3.4")
    assert scope["client"] == ("1.2.3.4", 43750)


def test_apply_real_client_ip_skips_same_or_none():
    """解析 IP 与直连方相同或为空时不改写"""
    scope = {"client": ("172.18.0.1", 43750)}
    apply_real_client_ip(SimpleNamespace(scope=scope), "172.18.0.1")
    assert scope["client"] == ("172.18.0.1", 43750)
    apply_real_client_ip(SimpleNamespace(scope=scope), None)
    assert scope["client"] == ("172.18.0.1", 43750)


def test_apply_real_client_ip_no_client():
    """client 为 None 时跳过（无法获取原直连方）"""
    scope = {}
    apply_real_client_ip(SimpleNamespace(scope=scope), "1.2.3.4")
    assert "client" not in scope


# ---------------------------------------------------------------------------
# 接管 uvicorn 原生访问日志
# ---------------------------------------------------------------------------


def test_disable_uvicorn_access_log():
    """关闭 uvicorn 原生访问日志：移除 handler 且禁止向上传播（协议层 hasHandlers 判定为 False）"""
    disable_uvicorn_access_log()
    uvicorn_access = logging.getLogger("uvicorn.access")
    assert uvicorn_access.handlers == []
    assert uvicorn_access.propagate is False


def test_setup_uvicorn_access_log_only_when_middleware_present():
    """仅装配了 LoggingMiddleware 的应用才接管 uvicorn.access，避免静默丢失原生访问日志"""
    with_middleware = FastAPI()
    LoggingMiddleware(with_middleware)
    setup_uvicorn_access_log(with_middleware)
    assert logging.getLogger("uvicorn.access").propagate is False

    # 未装配中间件的应用：setup 不干预 uvicorn.access（保持既有传播状态）
    logging.getLogger("uvicorn.access").propagate = True
    without = FastAPI()
    setup_uvicorn_access_log(without)
    assert logging.getLogger("uvicorn.access").propagate is True


# ---------------------------------------------------------------------------
# 日志中间件集成：访问日志输出真实客户端 IP（uvicorn 标准格式）
# ---------------------------------------------------------------------------


def _build_middleware_app() -> FastAPI:
    """构造装配访问日志中间件的应用（/whoami 回显 request.client.host 验证 scope 写回）"""
    app = FastAPI()
    app.add_middleware(LoggingMiddleware, service_name="test")

    @app.get("/whoami")
    async def whoami(request: Request):
        return {"client": request.client.host}

    return app


def test_access_log_uses_real_ip_when_trusted_proxy(monkeypatch, caplog):
    """可信代理直连 + X-Real-IP：访问日志与 scope["client"] 均为真实客户端 IP"""
    monkeypatch.setattr(IPAddressUtil, "is_trusted_proxy", staticmethod(lambda ip: True))
    client = TestClient(_build_middleware_app())
    with caplog.at_level(logging.INFO):
        resp = client.get("/whoami", headers={"x-real-ip": "1.2.3.4"})
    assert resp.status_code == 200
    assert resp.json()["client"] == "1.2.3.4"  # apply_real_client_ip 已写回 scope["client"]
    messages = [r.getMessage() for r in caplog.records]
    assert any("1.2.3.4:50000" in m and '"GET /whoami HTTP/1.1"' in m for m in messages)


def test_access_log_ignores_x_real_ip_when_untrusted(caplog):
    """不可信直连方忽略 X-Real-IP（防伪造），访问日志显示直连方地址"""
    client = TestClient(_build_middleware_app())
    with caplog.at_level(logging.INFO):
        resp = client.get("/whoami", headers={"x-real-ip": "1.2.3.4"})
    assert resp.status_code == 200
    assert resp.json()["client"] == "testclient"
    messages = [r.getMessage() for r in caplog.records]
    assert any("testclient:50000" in m and '"GET /whoami HTTP/1.1"' in m for m in messages)
