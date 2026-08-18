"""
FastAPI 集成

@Author: 花海
@Date: 2026/08/14 10:00
@Description: FastAPI 集成能力聚合导出：请求上下文中间件、大整数 JSON 响应、CORS、安全响应头、访问日志中间件。
"""
from web_infra.infra.web.request_context_middleware import RequestContextMiddleware, TraceIdMiddleware
from web_infra.infra.web.json_response import BigIntJSONResponse
from web_infra.infra.web.cors_config import setup_cors
from web_infra.infra.web.security_headers_middleware import SecurityHeadersMiddleware
from web_infra.infra.web.logging_middleware import LoggingMiddleware, setup_logging_middleware
from web_infra.infra.web.health import register_health_endpoints
from web_infra.infra.web.sse import format_sse, format_sse_error, sse_response
from web_infra.infra.web.idempotency_store_interface import IdempotencyResult, IdempotencyStoreInterface
from web_infra.infra.web.in_memory_idempotency_store import InMemoryIdempotencyStore
from web_infra.infra.web.redis_idempotency_store import RedisIdempotencyStore
from web_infra.infra.web.idempotency_middleware import IdempotencyMiddleware
from web_infra.infra.web.auth_middleware import AuthMiddleware
from web_infra.infra.web.rate_limit_middleware import RateLimitMiddleware
from web_infra.infra.web.diagnostic_access import DiagnosticAccessGuard

__all__ = [
    "RequestContextMiddleware",
    "TraceIdMiddleware",
    "BigIntJSONResponse",
    "setup_cors",
    "SecurityHeadersMiddleware",
    "LoggingMiddleware",
    "setup_logging_middleware",
    "register_health_endpoints",
    "format_sse",
    "format_sse_error",
    "sse_response",
    "IdempotencyResult",
    "IdempotencyStoreInterface",
    "InMemoryIdempotencyStore",
    "RedisIdempotencyStore",
    "IdempotencyMiddleware",
    "AuthMiddleware",
    "RateLimitMiddleware",
    "DiagnosticAccessGuard",
]
