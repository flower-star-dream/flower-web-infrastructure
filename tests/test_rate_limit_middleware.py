"""
统一入口限流中间件单元测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证限流中间件（规范 §7.3）：超限返回 429 + Retry-After + E1-RATE-000、
              路径维度独立限流、用户维度限流（读取 RequestContext 用户身份）。
"""
import httpx
import pytest
from fastapi import FastAPI

from web_infra.infra.context import RequestContext
from web_infra.infra.web import RateLimitMiddleware


def _build_app(qps: float = 100.0, burst: float = 50.0, key_by: str = "path") -> FastAPI:
    """构造带限流中间件的测试应用"""
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, qps=qps, burst=burst, key_by=key_by)

    @app.get("/ping")
    async def ping():
        return {"pong": True}

    @app.get("/orders")
    async def orders():
        return {"orders": []}

    return app


@pytest.mark.asyncio
async def test_rate_limit_429_with_retry_after():
    """耗尽令牌后返回 429 + Retry-After + E1-RATE-000（Result 结构）"""
    # qps=0 表示无补充，仅初始 burst 个令牌，保证测试确定性
    app = _build_app(qps=0.0, burst=2.0)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/ping")).status_code == 200
        assert (await client.get("/ping")).status_code == 200
        resp = await client.get("/ping")
        assert resp.status_code == 429
        assert int(resp.headers["Retry-After"]) >= 1
        body = resp.json()
        assert body["code"] == "E1-RATE-000"
        assert body["data"] is None


@pytest.mark.asyncio
async def test_rate_limit_path_dimension_independent():
    """路径维度限流：不同路径互不影响"""
    app = _build_app(qps=0.0, burst=1.0)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/ping")).status_code == 200
        assert (await client.get("/ping")).status_code == 429
        assert (await client.get("/orders")).status_code == 200  # 另一路径独立配额


@pytest.mark.asyncio
async def test_rate_limit_user_dimension():
    """用户维度限流：key_by=user 时按用户独立配额，匿名退化为路径维度"""
    app = _build_app(qps=0.0, burst=1.0, key_by="user")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        RequestContext.set_user_id("u1")
        assert (await client.get("/ping")).status_code == 200
        assert (await client.get("/ping")).status_code == 429  # u1 超限
        RequestContext.set_user_id("u2")
        assert (await client.get("/ping")).status_code == 200  # u2 独立配额
