"""
统一鉴权中间件

@Author: 花海
@Date: 2026/08/14 20:00
@Description: 统一入口鉴权中间件（规范 §6.4：认证校验在统一入口完成，业务模块不直接对接认证中心）。
              - 解析 Authorization: Bearer <token> 并校验（默认 JWTUtil，可注入 OAuth2 等校验器）
              - 校验失败返回 401（E2-AUTH-000/001/002），不进入业务模块
              - 校验成功注入请求上下文（user_id/scope/client_id），业务从上下文取身份，禁止自行解析凭证
              - 白名单路径（匿名访问）与 OPTIONS 预检放行
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from web_infra.constants import HttpStatusConstant
from web_infra.context import RequestContext
from web_infra.error import BizException, CommonErrorCode
from web_infra.monitoring.phase_timer import PhaseTimer
from web_infra.security.jwt_util import JWTUtil
from web_infra.security.token_verify_status_enum import TokenVerifyStatus


class AuthMiddleware:
    """统一入口鉴权中间件（认证 + 注入上下文，粗粒度授权由 PermissionGuard 声明式控制）"""

    def __init__(
        self,
        app: ASGIApp,
        *,
        token_verifier: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
        whitelist: tuple[str, ...] = ("/health", "/metrics", "/docs", "/redoc", "/openapi.json"),
        bearer_prefix: str = "Bearer ",
        excluded_methods: tuple[str, ...] = ("OPTIONS",),
    ) -> None:
        """初始化鉴权中间件。

        :param token_verifier: 令牌校验器 `(token) -> payload`（默认 JWTUtil.verify_token；
            接入 OAuth2 时注入 OAuth2TokenService.verify_token）
        :param whitelist: 匿名白名单路径（按前缀匹配，如 /health、/docs）
        :param bearer_prefix: Bearer 前缀（默认 "Bearer "）
        :param excluded_methods: 跳过鉴权的方法（默认 OPTIONS 预检）
        """
        self.app = app
        self._token_verifier = token_verifier
        self._whitelist = whitelist
        self._bearer_prefix = bearer_prefix
        self._excluded_methods = excluded_methods

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """请求入口：白名单/预检放行；其余校验 Bearer 凭证并注入上下文"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        path = scope.get("path", "")
        method = scope.get("method", "GET")

        if method in self._excluded_methods or self._is_whitelisted(path):
            await self.app(scope, receive, send)
            return

        auth = headers.get("authorization")
        token = auth[len(self._bearer_prefix):] if auth and auth.startswith(self._bearer_prefix) else None
        if not token:
            PhaseTimer.mark("auth")
            await self._send_unauthorized(send, CommonErrorCode.AUTH_UNAUTHENTICATED.code, "未认证：缺少 Bearer 凭证")
            return

        payload, error_code, error_message = await self._verify(token)
        if payload is None:
            PhaseTimer.mark("auth")
            await self._send_unauthorized(
                send, error_code or CommonErrorCode.AUTH_INVALID.code, error_message or "凭证校验失败"
            )
            return

        # 校验成功：注入请求上下文（§6.4 业务禁止自行解析凭证，统一从上下文取身份）
        RequestContext.set_user_id(str(payload.get("sub") or ""))
        RequestContext.set_scope(str(payload.get("scope") or ""))
        RequestContext.set_client_id(str(payload.get("client_id") or ""))
        PhaseTimer.mark("auth")
        try:
            await self.app(scope, receive, send)
        finally:
            RequestContext.clear()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _is_whitelisted(self, path: str) -> bool:
        """白名单路径：精确匹配或前缀匹配"""
        return any(path == item or path.startswith(item) for item in self._whitelist)

    async def _verify(self, token: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
        """校验令牌：返回 (payload, error_code, error_message)；成功时后两者为 None"""
        try:
            if self._token_verifier is not None:
                payload = await self._token_verifier(token)
                return payload, None, None
            payload, status = await JWTUtil.verify_token(token)
            if status == TokenVerifyStatus.EXPIRED:
                return None, CommonErrorCode.AUTH_EXPIRED.code, "凭证已过期"
            if status == TokenVerifyStatus.EXPIRING:
                # 凭证即将过期（规范 §6.1 静默刷新信号）：同 VALID 放行，由客户端凭响应头触发静默刷新
                return payload, None, None
            if status != TokenVerifyStatus.VALID:
                return None, CommonErrorCode.AUTH_INVALID.code, "凭证非法或已被撤销"
            return payload, None, None
        except BizException as exc:
            return None, exc.code, str(exc.message or "凭证校验失败")
        except Exception:
            return None, CommonErrorCode.AUTH_INVALID.code, "凭证非法或已被撤销"

    async def _send_unauthorized(self, send: Send, code: str, message: str) -> None:
        """发送 401 JSON 响应（规范 §6.4：校验失败统一入口直接返回，不进入业务模块）"""
        body = json.dumps({"code": code, "message": message, "data": None}, ensure_ascii=False).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": HttpStatusConstant.HTTP_UNAUTHORIZED,
                "headers": [(b"content-type", b"application/json; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": body})
