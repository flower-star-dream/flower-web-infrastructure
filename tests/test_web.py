"""
FastAPI 集成单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证全局异常处理与请求上下文中间件（规范 §4.7 / §6.4 / §17.4）。
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web_infra import (
    Result,
    CommonErrorCode,
    register_global_exception_handlers,
    RequestContext,
    TraceIdMiddleware,
)


def _build_app() -> FastAPI:
    """构建测试应用"""
    app = FastAPI()
    app.add_middleware(TraceIdMiddleware)
    register_global_exception_handlers(app)

    @app.get("/ok")
    def ok():
        return Result.success(data={"traceId": RequestContext.get_trace_id()})

    @app.get("/biz")
    def biz():
        raise CommonErrorCode.COMMON_NOT_FOUND.to_exception()

    @app.get("/lock")
    def lock():
        raise CommonErrorCode.LOCK_FAILED.to_exception()

    @app.get("/boom")
    def boom():
        raise RuntimeError("unexpected")

    return app


def test_success_and_trace_id_injected():
    """成功响应 + TraceId 注入请求上下文"""
    client = TestClient(_build_app())
    resp = client.get("/ok")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "S0000"
    assert body["data"]["traceId"]  # 中间件已生成 TraceId
    # 响应头回写 TraceId
    assert resp.headers.get("X-Trace-Id")


def test_biz_exception_maps_to_result():
    """业务异常映射为统一响应结构"""
    client = TestClient(_build_app())
    resp = client.get("/biz")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "E4-COMMON-000"
    assert body["data"] is None


def test_e3_exception_converged_at_boundary():
    """E3 类业务异常出网收敛：body.code 隐藏子类与编号（规范 §4.6.1）"""
    client = TestClient(_build_app())
    resp = client.get("/lock")
    assert resp.status_code == 423  # HTTP 状态码原样透传
    body = resp.json()
    assert body["code"] == "E3"
    assert body["message"] == "服务暂时不可用，请稍后重试"


def test_unexpected_exception_converged_to_e5():
    """未捕获异常兜底 E5-SYS-000，出网收敛为大类码 E5（HTTP 500）"""
    # FastAPI 将 Exception 处理器承载于 ServerErrorMiddleware，
    # 发送响应后仍会 re-raise，故关闭 TestClient 的异常抛出以校验响应
    client = TestClient(_build_app(), raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "E5"
    assert body["message"] == "系统繁忙，请稍后重试"
