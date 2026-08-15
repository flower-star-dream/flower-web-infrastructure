"""
SSE 流式响应封装单元测试

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 验证 SSE 分片格式、心跳保活、客户端断开取消传播（关闭生成器触发 finally）。
"""
import asyncio
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web_infra.web import format_sse, sse_response


class _FakeRequest:
    """模拟 FastAPI Request：可配置第 N 次检查后判定断开"""

    def __init__(self, disconnect_after: int) -> None:
        self._check_count = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._check_count += 1
        return self._check_count > self._disconnect_after


def _build_app() -> FastAPI:
    """构建 SSE 测试应用"""
    app = FastAPI()

    async def _events() -> AsyncIterator[dict]:
        yield {"type": "delta", "content": "你好"}
        yield {"type": "delta", "content": "世界"}
        yield {"type": "finish", "reason": "stop"}

    from fastapi import Request

    @app.get("/sse")
    async def sse(request: Request):
        return sse_response(_events(), request)

    return app


def test_format_sse_dict_and_str():
    """SSE 单帧格式化：dict 序列化 JSON、str 原样"""
    assert format_sse({"a": 1}) == 'data: {"a":1}\n\n'
    assert format_sse("plain") == "data: plain\n\n"


def test_sse_frames_format():
    """SSE 分片格式与响应头"""
    client = TestClient(_build_app())
    resp = client.get("/sse")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    text = resp.text
    assert 'data: {"type":"delta","content":"你好"}' in text
    assert 'data: {"type":"delta","content":"世界"}' in text
    assert 'data: {"type":"finish","reason":"stop"}' in text
    assert text.endswith("\n\n")


def test_sse_heartbeat_when_silent():
    """空闲超过心跳间隔发送心跳事件"""
    app = FastAPI()

    async def slow_events() -> AsyncIterator[dict]:
        yield {"type": "start"}
        await asyncio.sleep(0.15)  # 超过心跳间隔 0.05s
        yield {"type": "end"}

    from fastapi import Request

    @app.get("/sse-slow")
    async def sse_slow(request: Request):
        return sse_response(slow_events(), request, heartbeat_interval=0.05)

    client = TestClient(app)
    text = client.get("/sse-slow").text
    assert 'data: {"type":"heartbeat"}' in text  # 空闲期补发心跳
    assert 'data: {"type":"start"}' in text


def test_sse_disconnect_cancels_generator():
    """客户端断开：生成器被关闭（finally 执行），实现取消传播"""
    import asyncio as _asyncio

    closed = []

    async def cancellable_events() -> AsyncIterator[dict]:
        try:
            while True:
                yield {"type": "chunk", "content": "x"}
                await asyncio.sleep(0.05)
        finally:
            closed.append(True)

    async def run() -> None:
        request = _FakeRequest(disconnect_after=2)  # 第 3 次检查时判定断开
        response = sse_response(cancellable_events(), request, heartbeat_interval=0.5)
        frames: list[str] = []
        async for frame in response.body_iterator:
            frames.append(frame)
        # 流结束后生成器应被关闭
        assert closed, "客户端断开后生成器应被关闭（触发 finally）"
        assert len(frames) >= 2

    asyncio.run(run())
