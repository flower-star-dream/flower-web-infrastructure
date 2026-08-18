"""
API 幂等键中间件单元测试

@Author: 花海
@Date: 2026/08/14 18:30
@Description: 验证幂等占用/结果重放/占用中 202/业务异常释放（规范 §12.6）。
              使用 httpx ASGITransport 与应用共用同一事件循环，便于直接操作内存存储。
"""
import time

import httpx
import pytest

from web_infra.infra.web import IdempotencyMiddleware, InMemoryIdempotencyStore


def _build_app(store: InMemoryIdempotencyStore):
    """构造带幂等中间件的测试应用"""
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware, store=store)

    @app.post("/orders")
    async def create_order():
        return {"order_id": "order-1"}

    @app.get("/ping")
    async def ping():
        return {"pong": True}

    return app


@pytest.mark.asyncio
async def test_first_request_caches_result_and_replay():
    """首次请求缓存结果，重复请求直接重放且业务不重复执行"""
    store = InMemoryIdempotencyStore()
    app = _build_app(store)
    transport = httpx.ASGITransport(app=app)

    headers = {"Idempotency-Key": "key-001"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/orders", headers=headers)
        assert first.status_code == 200
        assert first.json() == {"order_id": "order-1"}

        second = await client.post("/orders", headers=headers)
        assert second.status_code == 200
        assert second.json() == {"order_id": "order-1"}


@pytest.mark.asyncio
async def test_without_idempotency_key_not_intercepted():
    """无幂等键时不启用幂等（正常执行）"""
    store = InMemoryIdempotencyStore()
    app = _build_app(store)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/orders")).status_code == 200
        assert (await client.get("/ping")).status_code == 200  # GET 不受影响


@pytest.mark.asyncio
async def test_inflight_duplicate_returns_202():
    """占用中重复请求返回 202（规范禁止 409）"""
    store = InMemoryIdempotencyStore()
    app = _build_app(store)
    transport = httpx.ASGITransport(app=app)

    await store.try_occupy("idem:anonymous:key-002", 60)  # 模拟首次请求处理中
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/orders", headers={"Idempotency-Key": "key-002"})
        assert response.status_code == 202


@pytest.mark.asyncio
async def test_business_error_releases_occupancy():
    """业务异常释放占用：后续请求可正常重试"""
    store = InMemoryIdempotencyStore()
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware, store=store)
    calls = {"n": 0}

    @app.post("/flaky")
    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {"ok": True}

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"Idempotency-Key": "key-003"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/flaky", headers=headers)).status_code == 500  # 首次失败
        assert (await client.post("/flaky", headers=headers)).status_code == 200  # 占用已释放，重试成功


@pytest.mark.asyncio
async def test_store_ttl_expires_result():
    """结果 TTL 过期后可重新占用执行"""
    store = InMemoryIdempotencyStore()
    app = _build_app(store)
    transport = httpx.ASGITransport(app=app)

    headers = {"Idempotency-Key": "key-004"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/orders", headers=headers)).status_code == 200
        # 模拟结果过期
        async with store._lock:
            for key in list(store._results):
                result, _ = store._results[key]
                store._results[key] = (result, time.monotonic() - 1)
        assert (await client.post("/orders", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_replay_with_same_body_replayed():
    """幂等键复用且请求体一致：重放首次结果（整改 S12-1 摘要纳入请求体）"""
    store = InMemoryIdempotencyStore()
    app = _build_app(store)
    transport = httpx.ASGITransport(app=app)

    headers = {"Idempotency-Key": "key-005"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/orders", headers=headers, json={"sku": "a", "qty": 1})
        assert first.status_code == 200
        second = await client.post("/orders", headers=headers, json={"sku": "a", "qty": 1})
        assert second.status_code == 200
        assert second.json() == {"order_id": "order-1"}


@pytest.mark.asyncio
async def test_replay_with_different_body_rejected_409():
    """幂等键复用但请求体不同：返回 409 提示更换幂等键（整改 S12-1 一致性校验）"""
    store = InMemoryIdempotencyStore()
    app = _build_app(store)
    transport = httpx.ASGITransport(app=app)

    headers = {"Idempotency-Key": "key-006"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/orders", headers=headers, json={"sku": "a"})).status_code == 200
        resp = await client.post("/orders", headers=headers, json={"sku": "b"})
        assert resp.status_code == 409
        body = resp.json()
        assert body["code"] == "E4-COMMON-001"
        assert "更换幂等键" in body["message"]


@pytest.mark.asyncio
async def test_replay_with_different_query_rejected_409():
    """幂等键复用但查询参数不同：同样触发 409（摘要含 query）"""
    store = InMemoryIdempotencyStore()
    app = _build_app(store)
    transport = httpx.ASGITransport(app=app)

    headers = {"Idempotency-Key": "key-007"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/orders?source=app", headers=headers)).status_code == 200
        resp = await client.post("/orders?source=web", headers=headers)
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_inflight_duplicate_with_body_still_202():
    """占用中重复请求（含请求体）仍返回 202，不比对摘要"""
    store = InMemoryIdempotencyStore()
    app = _build_app(store)
    transport = httpx.ASGITransport(app=app)

    await store.try_occupy("idem:anonymous:key-008", 60)  # 模拟首次请求处理中
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/orders", headers={"Idempotency-Key": "key-008"}, json={"sku": "x"})
        assert response.status_code == 202
