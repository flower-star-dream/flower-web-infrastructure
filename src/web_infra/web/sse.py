"""
SSE 流式响应封装

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 服务端推送事件（SSE）统一传输层封装（AI 规范 §9）：
              统一 `data: {json}\n\n` 分片格式、心跳保活（≤15s）、客户端断开取消传播（关闭生成器触发调用方 finally）、
              TraceId 由调用方在事件体内透传。传输层与业务分片内容解耦，事件内容由调用方生成器决定。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, AsyncIterator, Awaitable, Callable

from fastapi import Request
from fastapi.responses import StreamingResponse

from web_infra.constants import InfraConstant

# SSE 心跳事件（规范 §9：心跳保活 ≤15s，防止中间层断连）
HEARTBEAT_EVENT = {"type": "heartbeat"}


def format_sse(data: dict[str, Any] | str, *, event: str | None = None) -> str:
    """将事件格式化为 SSE 文本帧。

    :param data: 事件内容（dict 序列化为 JSON，str 原样输出）
    :param event: 可选事件名（如 "error"，输出 `event: xxx` 行；默认无事件名）
    :return: `[event: {name}\n]data: {content}\n\n`
    """
    if isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {payload}\n\n"


def format_sse_error(code: str, message: str) -> str:
    """格式化流内错误分片（AI 规范 §10：流开始后的异常通过 `event: error` 终止并携带错误码）。

    输出格式：
        event: error
        data: {"code": "E4-AI-002", "message": "..."}
        （空行）
    """
    return format_sse({"code": code, "message": message}, event="error")


def sse_response(
    events: AsyncGenerator[dict[str, Any], None],
    request: Request,
    heartbeat_interval: float = 15.0,
    headers: dict[str, str] | None = None,
) -> StreamingResponse:
    """将异步事件生成器包装为 SSE StreamingResponse。

    :param events: 异步事件生成器（AsyncGenerator），逐个产出事件（dict 序列化为 JSON）
    :param request: 请求对象，用于检测客户端断开
    :param heartbeat_interval: 心跳间隔（秒），默认 15s（规范 §9）
    :param headers: 追加响应头（默认附带 SSE 标准头）
    :return: StreamingResponse（media_type=text/event-stream）
    """
    base_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    if headers:
        base_headers.update(headers)

    async def _stream() -> AsyncIterator[str]:
        """事件流主体：发送事件 + 心跳保活 + 断开取消传播"""
        try:
            while True:
                # 每次迭代检测客户端断开，及时释放底层资源（规范 §9）
                if await request.is_disconnected():
                    break
                try:
                    # 等待下一事件；超时未到事件则发送心跳
                    event = await asyncio.wait_for(events.__anext__(), timeout=heartbeat_interval)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    yield format_sse(HEARTBEAT_EVENT)
                    continue
                yield format_sse(event)
        finally:
            # 关闭生成器：触发调用方生成器 finally，实现取消传播（释放底层流式资源）
            await events.aclose()

    return StreamingResponse(_stream(), media_type=InfraConstant.INFRA_SSE_MEDIA_TYPE, headers=base_headers)


# 兼容类型别名：事件源可为 async generator 或返回 AsyncIterator 的工厂
SSEEventSource = AsyncIterator[dict[str, Any]] | Callable[[], Awaitable[AsyncIterator[dict[str, Any]]]]
