"""
统一入口限流中间件

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 统一入口限流中间件（规范 §7.3 令牌桶平滑限流）：
              - 按路径维度（method:path）或用户维度（user_id + method:path）令牌桶限流
              - 超限返回 429 + Retry-After 响应头 + 统一 Result 结构（E1-RATE-000，已注册于错误码表）
              - 用户维度需在统一鉴权之后执行：yml 中 rate_limit 声明于 auth 之前（Starlette 后声明者外层先执行），
                未启用统一鉴权时读不到用户身份，自动退化为路径维度
"""
from __future__ import annotations

import json
import math
from collections import OrderedDict
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from web_infra.infra.context import ANONYMOUS_USER, RequestContext
from web_infra.infra.error.common_error_code import CommonErrorCode
from web_infra.infra.resilience.rate_limit_config import RateLimitConfig
from web_infra.infra.resilience.token_bucket_rate_limiter import TokenBucketRateLimiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """统一入口限流中间件：按路径/用户维度令牌桶限流（规范 §7.3）"""

    def __init__(
        self,
        app: Any,
        *,
        qps: float | None = None,
        burst: float | None = None,
        key_by: str = "path",
        max_limiters: int = 10000,
    ) -> None:
        """初始化限流中间件。

        :param app: 下游 ASGI 应用
        :param qps: 每秒令牌补充速率（默认 100，配置缺省回落）
        :param burst: 桶容量/允许突发量（默认 50，配置缺省回落）
        :param key_by: 限流维度："path"（按路径）或 "user"（按用户+路径，需在统一鉴权之后执行）
        :param max_limiters: 令牌桶数量上限（默认 10000；user 维度下每个新用户新建一个桶，
            超限后按 LRU 淘汰最久未访问的桶，防止内存无限增长）
        """
        super().__init__(app)
        self._qps = 100.0 if qps is None else qps
        self._burst = 50.0 if burst is None else burst
        if key_by not in ("path", "user"):
            raise ValueError("key_by 仅支持 path 或 user")
        self._key_by = key_by
        # OrderedDict 记录访问序（LRU 语义），容量受限防内存无限增长
        self._limiters: OrderedDict[str, TokenBucketRateLimiter] = OrderedDict()
        self._max_limiters = max_limiters

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """请求分发：按维度 Key 取令牌，超限返回 429 + Retry-After，否则放行"""
        key = self._build_key(request)
        limiter = self._limiter_for(key)
        if not limiter.try_acquire():
            return self._rate_limited_response(limiter.retry_after_seconds())
        return await call_next(request)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _limiter_for(self, key: str) -> TokenBucketRateLimiter:
        """获取（或创建）指定 Key 的令牌桶：LRU 语义 + 数量上限（防内存无限增长）。

        桶数量达到上限时淘汰最久未访问的桶；调用方为单事件循环（ASGI 中间件），
        桶表操作无 await 挂起点，天然原子。
        """
        limiter = self._limiters.get(key)
        if limiter is None:
            limiter = TokenBucketRateLimiter(
                "rate-limit",
                RateLimitConfig(qps=self._qps, burst=self._burst),
            )
            self._limiters[key] = limiter
            while len(self._limiters) > self._max_limiters:
                self._limiters.popitem(last=False)  # 淘汰最久未访问
        else:
            self._limiters.move_to_end(key)
        return limiter

    def _build_key(self, request: Request) -> str:
        """构造限流维度 Key：路径维度为 method:path；用户维度追加 user_id（匿名退化为路径维度）"""
        base = f"{request.method}:{request.url.path}"
        if self._key_by != "user":
            return base
        user_id = RequestContext.get_user_id()
        if not user_id or user_id == ANONYMOUS_USER:
            return base
        return f"{user_id}:{base}"

    @staticmethod
    def _rate_limited_response(retry_after: float) -> Response:
        """构造 429 响应：Retry-After 头 + 统一 Result 结构（E1-RATE-000）"""
        seconds = str(math.ceil(retry_after)) if math.isfinite(retry_after) else "60"
        body = json.dumps(
            {
                "code": CommonErrorCode.RATE_LIMITED.code,
                "message": CommonErrorCode.RATE_LIMITED.message,
                "data": None,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        return Response(
            status_code=CommonErrorCode.RATE_LIMITED.http_status,
            content=body,
            media_type="application/json",
            headers={"Retry-After": seconds},
        )
