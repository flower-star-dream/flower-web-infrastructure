"""
对外契约测试（规范 §11.2 消费者驱动契约 CDC 轻量落地，审查项 S11-1）

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 将对外契约固化为可执行断言（契约即代码），随 pytest 全量执行自动纳入 CI 门禁，
              防止接口结构被无意破坏。契约清单：
              1. Result 统一响应结构（必含 code/message/data，成功 code=S0000，失败 data=null）——规范 §4.7
              2. PageResult 分页结构（data.list 数组 + data.total 整数，JSON 键名确为 list/total）——规范 §12.3
              3. 错误码格式（E<大类>-<子类>-<3位编号> / S0000）与 HTTP 状态码大类推导——规范 §4.1/§4.2
              4. 边界收敛（E3/E5 出网收敛为大类码，E1/E2/E4 透传）——规范 §4.6.1
              5. /health 与 /metrics 端点响应契约——规范 §19.4 / §18.1
              6. HTTP 异常映射（404->E4-COMMON-000，405->E1-HTTP-000）——规范 §4.2
              7. 幂等占用中返回 202：由 tests/test_idempotency_middleware.py 的
                 test_inflight_duplicate_returns_202 覆盖（规范 §12.6），此处引用不重复断言。
"""
from __future__ import annotations

import json
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web_infra.error import (
    ErrorCodeRegistry,
    converge_error_code,
    derive_http_status,
    parse_category,
)
from web_infra.error.handler import register_global_exception_handlers
from web_infra.result import PageResult, Result
from web_infra.web import register_health_endpoints

# 错误码格式契约（规范 §4.1/§4.2）：E<大类>-<子类>-<3位编号> 或成功码 S0000
ERROR_CODE_PATTERN = re.compile(r"^(E[1-5]-(?:[A-Z]+)-[0-9]{3}|S0000)$")


def _build_contract_app() -> FastAPI:
    """构建契约测试应用：注册健康/指标端点与全局异常处理器，并提供一个 GET-only 路由供 405 断言"""
    app = FastAPI()
    register_health_endpoints(app, components={}, service_name="contract-test")
    register_global_exception_handlers(app)

    @app.get("/only-get")
    def only_get() -> dict:
        return {"ok": True}

    return app


# ---------------------------------------------------------------------------
# 契约 1：Result 统一响应结构（规范 §4.7）
# ---------------------------------------------------------------------------


def test_contract_result_success_shape():
    """契约：成功响应 JSON 必含 code/message/data 三键，且 code 恒为 S0000（规范 §4.7）"""
    dumped = json.loads(Result.success(data={"id": 1}).model_dump_json())
    assert set(dumped.keys()) == {"code", "message", "data"}
    assert dumped["code"] == "S0000"
    assert dumped["message"] == "ok"
    assert dumped["data"] == {"id": 1}


def test_contract_result_failure_data_null():
    """契约：失败响应 data 恒为 null，code 为业务错误码（规范 §4.7）"""
    dumped = json.loads(Result.failure("E4-ORDER-001", "订单不存在").model_dump_json())
    assert dumped["code"] == "E4-ORDER-001"
    assert dumped["message"] == "订单不存在"
    assert dumped["data"] is None


# ---------------------------------------------------------------------------
# 契约 2：PageResult 分页结构（规范 §12.3）
# ---------------------------------------------------------------------------


def test_contract_page_result_list_and_total_keys():
    """契约：分页响应 JSON 中 data.list 为数组、data.total 为整数，键名确为 list/total（规范 §12.3）"""
    page = PageResult.success(records=[{"id": 1}, {"id": 2}], total=2)
    dumped = json.loads(page.model_dump_json(by_alias=True))
    data = dumped["data"]
    assert set(data.keys()) == {"list", "total"}
    assert isinstance(data["list"], list)
    assert isinstance(data["total"], int)
    assert data["total"] == 2
    assert data["list"] == [{"id": 1}, {"id": 2}]


# ---------------------------------------------------------------------------
# 契约 3：错误码格式与 HTTP 状态码大类推导（规范 §4.1/§4.2/§4.2.1）
# ---------------------------------------------------------------------------


def test_contract_error_code_format():
    """契约：全部注册错误码匹配 E<大类>-<子类>-<3位编号> 或 S0000，且大类解析一致（规范 §4.1/§4.2）"""
    registered = ErrorCodeRegistry._codes
    assert registered, "错误码注册表不应为空"
    for code, error_code in registered.items():
        assert ERROR_CODE_PATTERN.match(code) is not None, f"错误码格式违反契约: {code}"
        assert parse_category(code) == error_code.category, f"错误码大类解析不一致: {code}"


def test_contract_http_status_category_derivation():
    """契约：HTTP 状态码按大类推导（E1->400 / E2->401 / E2-PERM->403 / E3->500 / E3-LOCK->423 / E4->422 / E5->500，规范 §4.2/§4.2.1）"""
    assert derive_http_status("E1-PARAM-000") == 400
    assert derive_http_status("E2-AUTH-000") == 401
    assert derive_http_status("E2-PERM-000") == 403
    assert derive_http_status("E3-DB-000") == 500
    assert derive_http_status("E3-LOCK-000") == 423
    assert derive_http_status("E4-ORDER-001") == 422
    assert derive_http_status("E5-SYS-000") == 500
    # 成功码恒为 200
    assert derive_http_status("S0000") == 200


# ---------------------------------------------------------------------------
# 契约 4：边界收敛（规范 §4.6.1）
# ---------------------------------------------------------------------------


def test_contract_converge_e3_e5_to_category_code():
    """契约：E3/E5 出网收敛为大类前缀码 + 大类默认文案，隐藏子类与编号（规范 §4.6.1）"""
    e3_code, e3_message = converge_error_code("E3-LOCK-000", "锁获取失败")
    assert e3_code == "E3"
    assert e3_message == "服务暂时不可用，请稍后重试"
    e5_code, e5_message = converge_error_code("E5-SYS-000", "系统未知异常")
    assert e5_code == "E5"
    assert e5_message == "系统繁忙，请稍后重试"


def test_contract_converge_pass_through_e1_e2_e4():
    """契约：E1/E2/E4 出网透传完整错误码与文案，不收敛（规范 §4.6.1）"""
    for code, message in (
        ("E1-PARAM-000", "参数错误"),
        ("E2-AUTH-000", "未认证"),
        ("E4-ORDER-001", "订单不存在"),
    ):
        conv_code, conv_message = converge_error_code(code, message)
        assert conv_code == code
        assert conv_message == message


# ---------------------------------------------------------------------------
# 契约 5：/health 与 /metrics 端点响应契约（规范 §19.4 / §18.1）
# ---------------------------------------------------------------------------


def test_contract_health_response_shape():
    """/health 契约：HTTP 200/503，body.status ∈ {UP, DOWN}，含 service 与 components 字典（规范 §19.4）"""
    client = TestClient(_build_contract_app())
    resp = client.get("/health")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert body["status"] in ("UP", "DOWN")
    assert isinstance(body["service"], str)
    assert isinstance(body["components"], dict)
    # 组件状态值域约束
    assert set(body["components"].values()) <= {"UP", "DOWN"}


def test_contract_metrics_response_shape():
    """/metrics 契约：Content-Type 为 text/plain 或 text/html，响应体含 Prometheus 指标命名片段（规范 §18.1）"""
    client = TestClient(_build_contract_app())
    # Prometheus 抓取（默认 Accept 无 text/html 偏好）：返回文本格式且含指标命名片段
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain") or resp.headers["content-type"].startswith("text/html")
    assert b"http_requests_total" in resp.content or b"_total" in resp.content
    # 浏览器（Accept 含 text/html）：返回 HTML 可视化页面
    html_resp = client.get("/metrics", headers={"Accept": "text/html,application/xhtml+xml"})
    assert html_resp.status_code == 200
    assert html_resp.headers["content-type"].startswith("text/html")


# ---------------------------------------------------------------------------
# 契约 6：HTTP 异常映射（规范 §4.2）
# ---------------------------------------------------------------------------


def test_contract_http_404_maps_to_e4_common():
    """契约：404 映射为 E4-COMMON-000，响应体为统一 Result 结构且 data 为 null（规范 §4.2）"""
    client = TestClient(_build_contract_app())
    resp = client.get("/not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert set(body.keys()) == {"code", "message", "data"}
    assert body["code"] == "E4-COMMON-000"
    assert body["data"] is None


def test_contract_http_405_maps_to_e1_http():
    """契约：405 映射为 E1-HTTP-000，响应体为统一 Result 结构（规范 §4.2）"""
    client = TestClient(_build_contract_app())
    resp = client.post("/only-get")
    assert resp.status_code == 405
    body = resp.json()
    assert set(body.keys()) == {"code", "message", "data"}
    assert body["code"] == "E1-HTTP-000"
    assert body["data"] is None
