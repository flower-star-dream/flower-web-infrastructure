"""
API 幂等键中间件

@Author: 花海
@Date: 2026/08/14 18:30
@Description: 写接口幂等键中间件（规范 §12.6）：
              POST/PATCH/PUT/DELETE 携带 Idempotency-Key 时，以「用户 + 幂等键」为唯一约束：
              首次请求原子占用并缓存处理结果，重复请求先比对请求摘要（method:path:query + 请求体哈希），
              摘要一致才重放首次结果（HTTP 200 + 原业务 code），摘要不一致返回 409 提示更换幂等键；
              处理中重复请求返回 202。TTL 覆盖重试窗口（默认 24h）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, cast

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from web_infra.infra.constants import HttpStatusConstant
from web_infra.infra.context import RequestContext
from web_infra.infra.error.common_error_code import CommonErrorCode
from web_infra.infra.web.idempotency_store_interface import IdempotencyResult, IdempotencyStoreInterface


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """API 幂等键中间件（服务端幂等表保障原子性，规范 §12.6）"""

    _KEY_PREFIX = "idem:"

    def __init__(
        self,
        app: Any,
        store: IdempotencyStoreInterface,
        *,
        ttl_seconds: int = 86400,
        header_name: str = "Idempotency-Key",
        methods: tuple[str, ...] = ("POST", "PATCH", "PUT", "DELETE"),
    ) -> None:
        """初始化幂等中间件。

        :param store: 幂等键存储（内存默认 / Redis 跨实例）
        :param ttl_seconds: 幂等结果保留时长（秒，默认 24h 覆盖重试窗口）
        :param header_name: 幂等键请求头名
        :param methods: 启用幂等的写方法集合
        """
        super().__init__(app)
        self._store = store
        self._ttl_seconds = ttl_seconds
        self._header_name = header_name
        self._methods = methods

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """请求分发：非幂等方法或无幂等键直接放行；否则执行幂等占用/摘要比对/重放逻辑"""
        idem_key = request.headers.get(self._header_name)
        if request.method not in self._methods or not idem_key:
            return await call_next(request)

        key = self._build_key(idem_key)
        request_hash = await self._build_request_hash(request)

        if not await self._store.try_occupy(key, self._ttl_seconds):
            return await self._replay_or_inflight(key, request_hash)

        try:
            response = await call_next(request)
        except Exception:
            await self._store.release(key)  # 业务异常：释放占用，允许客户端重试
            raise

        body_iterator = cast(Any, getattr(response, "body_iterator", None))
        body = b"".join([chunk async for chunk in body_iterator]) if body_iterator is not None else b""
        await self._store.set_result(
            key,
            IdempotencyResult(
                status_code=response.status_code,
                content_type=response.headers.get("content-type", "application/json"),
                body=body,
                request_hash=request_hash,
            ),
            self._ttl_seconds,
        )
        return Response(
            content=body,
            status_code=response.status_code,
            headers=response.headers,
            media_type=response.headers.get("content-type"),
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _build_key(self, idem_key: str) -> str:
        """幂等键按用户维度隔离（规范 §12.6：userId + Idempotency-Key 联合唯一）"""
        user_id = RequestContext.get_user_id()
        return f"{self._KEY_PREFIX}{user_id}:{idem_key}"

    async def _build_request_hash(self, request: Request) -> str:
        """请求摘要：method:path:query + 请求体 SHA-256（规范 §12.6 三要素之一）。

        Starlette BaseHTTPMiddleware 的 _CachedRequest 会缓存 body 并向下游重放，
        此处读取 body 不破坏请求流（stream 场景由框架兜底为空体）。
        """
        body = await request.body()
        digest = hashlib.sha256()
        digest.update(request.method.encode("utf-8"))
        digest.update(b"\n")
        digest.update(request.url.path.encode("utf-8"))
        digest.update(b"\n")
        digest.update(request.url.query.encode("utf-8"))
        digest.update(b"\n")
        digest.update(body)
        return digest.hexdigest()

    async def _replay_or_inflight(self, key: str, request_hash: str) -> Response:
        """重复请求：缓存结果且摘要一致才重放；摘要不一致返回 409（提示更换幂等键）；占用中返回 202"""
        result = await self._store.get_result(key)
        if result is not None:
            if result.request_hash != request_hash:
                # 幂等键被复用但请求内容不同：拒绝重放，提示更换幂等键（规范 §12.6 一致性校验）
                return Response(
                    status_code=CommonErrorCode.COMMON_CONFLICT.http_status,
                    content=json.dumps(
                        {
                            "code": CommonErrorCode.COMMON_CONFLICT.code,
                            "message": "幂等键已使用且请求内容不一致，请更换幂等键",
                            "data": None,
                        },
                        ensure_ascii=False,
                    ),
                    media_type="application/json",
                )
            return Response(
                content=result.body,
                status_code=result.status_code,
                media_type=result.content_type,
            )
        return Response(
            status_code=HttpStatusConstant.HTTP_ACCEPTED,
            content=json.dumps(
                {
                    "code": CommonErrorCode.COMMON_CONFLICT.code,
                    "message": "幂等请求处理中，请稍后重试",
                },
                ensure_ascii=False,
            ),
            media_type="application/json",
        )
