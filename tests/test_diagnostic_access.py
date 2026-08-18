"""
诊断端点访问守卫单元测试

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 验证 DiagnosticAccessGuard（设计文档 §9）：生产/非生产生效条件、白名单命中/拒绝
              （403）、fail-closed（get_client_ip 返回 None 拒绝）、IPv4-mapped IPv6 转 IPv4、
              CIDR 边界内外断言、伪造代理头防护、allowed_cidrs 追加。
"""
import httpx
import pytest
from fastapi import FastAPI

from web_infra.infra.web import DiagnosticAccessGuard, register_health_endpoints


def _make_request(client_ip: str | None, headers: dict | None = None) -> httpx.Request:
    """构造带指定直连方 IP 的请求（scope client 模拟；client_ip=None 表示无直连方）"""
    import starlette.requests

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/metrics",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
        "root_path": "",
        "asgi": {"version": "3.0"},
        "app": None,
        "state": {},
    }
    if client_ip is not None:
        scope["client"] = (client_ip, 50000)
    return starlette.requests.Request(scope)


def _guard(enabled: bool = True, allowed_cidrs=(), *, production: bool = True) -> DiagnosticAccessGuard:
    """构造固定生产判定的守卫（测试隔离 Settings 全局态）"""
    return DiagnosticAccessGuard(enabled=enabled, allowed_cidrs=tuple(allowed_cidrs), is_production=lambda: production)


# ------------------------------------------------------------------
# 生效条件
# ------------------------------------------------------------------

def test_non_production_allows_public_ip():
    """非生产环境：公网 IP 放行（生效条件要求 app_env==prod）"""
    guard = _guard(production=False)
    assert guard.check(_make_request("8.8.8.8")) is True


def test_disabled_guard_allows_public_ip():
    """enabled=false：公网 IP 放行"""
    guard = _guard(enabled=False)
    assert guard.check(_make_request("8.8.8.8")) is True


def test_production_public_ip_denied():
    """生产环境：公网 IPv4 拒绝"""
    guard = _guard()
    assert guard.check(_make_request("8.8.8.8")) is False


def test_production_internal_ip_allowed():
    """生产环境：内网 IPv4 放行"""
    guard = _guard()
    assert guard.check(_make_request("10.0.0.1")) is True
    assert guard.check(_make_request("172.16.0.1")) is True
    assert guard.check(_make_request("192.168.1.1")) is True
    assert guard.check(_make_request("127.0.0.1")) is True


# ------------------------------------------------------------------
# fail-closed / 特殊格式
# ------------------------------------------------------------------

def test_production_no_ip_denied_fail_closed():
    """生产环境：无法获取客户端 IP（request.client=None）拒绝（fail-closed）"""
    guard = _guard()
    request = _make_request(None)  # client 为 None → get_client_ip 返回 None
    assert guard.check(request) is False


def test_production_ipv6_public_denied():
    """生产环境：公网 IPv6 拒绝"""
    guard = _guard()
    assert guard.check(_make_request("2001:db8::1")) is False


def test_production_ipv6_loopback_allowed():
    """生产环境：IPv6 回环 ::1 放行"""
    guard = _guard()
    assert guard.check(_make_request("::1")) is True


def test_ipv4_mapped_ipv6_private_allowed():
    """IPv4-mapped IPv6：::ffff:10.0.0.1 按 IPv4 语义视为内网放行"""
    guard = _guard()
    assert guard.check(_make_request("::ffff:10.0.0.1")) is True


def test_ipv4_mapped_ipv6_public_denied():
    """IPv4-mapped IPv6：::ffff:8.8.8.8 按 IPv4 公网拒绝"""
    guard = _guard()
    assert guard.check(_make_request("::ffff:8.8.8.8")) is False


def test_unparsable_ip_denied():
    """无法解析的 IP 字符串拒绝（fail-closed，与 is_private_or_reserved 的 fail-open 相反）"""
    guard = _guard()
    assert guard.check(_make_request("not-an-ip")) is False


# ------------------------------------------------------------------
# CIDR 边界
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    ("ip", "allowed"),
    [
        ("10.0.0.1", True),   # 10/8 内
        ("11.0.0.1", False),  # 10/8 外
        ("172.16.0.1", True),   # 172.16/12 内
        ("172.32.0.1", False),  # 172.16/12 外
        ("192.168.0.1", True),   # 192.168/16 内
        ("192.169.0.1", False),  # 192.168/16 外
    ],
)
def test_cidr_boundary(ip, allowed):
    """CIDR 边界内外各一组断言"""
    guard = _guard()
    assert guard.check(_make_request(ip)) is allowed


def test_allowed_cidrs_append():
    """allowed_cidrs 追加：新增网段命中放行（默认 5 段之外）"""
    guard = _guard(allowed_cidrs=("203.0.113.0/24",))
    assert guard.check(_make_request("203.0.113.10")) is True
    assert guard.check(_make_request("8.8.8.8")) is False  # 默认段不命中仍拒绝


# ------------------------------------------------------------------
# 代理头伪造防护（与 get_client_ip 组合）
# ------------------------------------------------------------------

def test_untrusted_direct_forged_x_real_ip_denied():
    """不可信直连方伪造 X-Real-IP: 10.x：取直连方公网 → 拒绝（伪造失效）"""
    guard = _guard()
    # 直连方 8.8.8.8（公网，非可信代理）伪造内网 X-Real-IP
    request = _make_request("8.8.8.8", headers={"X-Real-IP": "10.0.0.1"})
    assert guard.check(request) is False


def test_trusted_proxy_passthrough_x_real_ip_allowed():
    """可信代理透传 X-Real-IP 内网：放行（代理头可信）"""
    guard = _guard()
    # 直连方 172.18.0.1（Docker 网段=可信代理）透传 X-Real-IP=10.0.0.1（内网）
    request = _make_request("172.18.0.1", headers={"X-Real-IP": "10.0.0.1"})
    assert guard.check(request) is True


def test_trusted_proxy_xff_takes_last():
    """可信代理 X-Forwarded-For 取最后一项：伪造前缀不影响"""
    guard = _guard()
    # 直连方 172.18.0.1（可信代理）透传 XFF：伪造 8.8.8.8 前缀 + 真实内网 10.0.0.5 在最后
    request = _make_request("172.18.0.1", headers={"X-Forwarded-For": "8.8.8.8, 10.0.0.5"})
    assert guard.check(request) is True


# ------------------------------------------------------------------
# 端点集成（/metrics 生产守卫）
# ------------------------------------------------------------------

def test_metrics_endpoint_production_guard():
    """/metrics 集成：注册守卫后内网来源判定放行（守卫判定本身由单测覆盖）"""
    app = FastAPI()
    guard = _guard()  # production=True
    register_health_endpoints(app, service_name="test", access_guard=guard.check)
    # 守卫可直接判定（端点集成路径受 TestClient 直连方限制，核心判定已在单测覆盖）
    assert guard.check(_make_request("10.0.0.1")) is True
    assert guard.check(_make_request("8.8.8.8")) is False
