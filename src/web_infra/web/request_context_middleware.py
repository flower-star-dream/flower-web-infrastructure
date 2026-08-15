"""
请求上下文中间件

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 请求上下文中间件，遵循规范 §6.4 / §17.4。
              统一入口生成/透传 TraceId，注入用户/客户端/服务标识到请求上下文，
              请求结束时清理上下文，避免上下文泄漏。
"""
from __future__ import annotations

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from web_infra.constants import (
    AUTH_HEADER_TRACE_ID,
    AUTH_HEADER_USER_ID,
    AUTH_HEADER_SCOPE,
    AUTH_HEADER_CLIENT_ID,
    AUTH_HEADER_SERVICE_ID,
    AUTH_HEADER_TENANT_ID,
)
from web_infra.context import RequestContext, generate_trace_id


class RequestContextMiddleware:
    """请求上下文中间件：生成/透传 TraceId，注入请求上下文，请求结束清理"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # 仅处理 HTTP 请求
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        # 上游已传 TraceId 则透传，否则统一入口生成（规范 §17.4）
        trace_id = headers.get(AUTH_HEADER_TRACE_ID) or generate_trace_id()

        # 注入请求上下文（用户链路 X-User-Id / 服务链路 X-Service-Id，规范 §6.5）。
        # 仅当请求头存在时注入，避免用空值覆盖身份；
        # 统一鉴权启用时由内层 AuthMiddleware 以 token payload 覆盖（payload 优先，规范 §6.4）。
        RequestContext.set_trace_id(trace_id)
        header_user_id = headers.get(AUTH_HEADER_USER_ID)
        if header_user_id:
            RequestContext.set_user_id(header_user_id)
        header_scope = headers.get(AUTH_HEADER_SCOPE)
        if header_scope:
            RequestContext.set_scope(header_scope)
        header_client_id = headers.get(AUTH_HEADER_CLIENT_ID)
        if header_client_id:
            RequestContext.set_client_id(header_client_id)
        header_service_id = headers.get(AUTH_HEADER_SERVICE_ID)
        if header_service_id:
            RequestContext.set_service_id(header_service_id)
        # 租户上下文（多租户扩展 §1.2：后端经 X-Tenant-Id 统一透传；仅请求头存在时注入）
        header_tenant_id = headers.get(AUTH_HEADER_TENANT_ID)
        if header_tenant_id:
            RequestContext.set_tenant_id(header_tenant_id)

        async def _send(message: Message) -> None:
            # 响应头回写 TraceId，便于客户端/下游关联链路
            if message["type"] == "http.response.start":
                mutable_headers = MutableHeaders(scope=message)
                mutable_headers[AUTH_HEADER_TRACE_ID] = trace_id
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            RequestContext.clear()


# 便捷别名
TraceIdMiddleware = RequestContextMiddleware
