"""
请求上下文模块

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 请求上下文能力聚合导出，遵循规范 §6.5（上下文传递）与 §17.4（链路追踪）。
"""
from web_infra.infra.context.request_context import (
    RequestContext,
    generate_trace_id,
    ANONYMOUS_USER,
    SYSTEM_USER,
)
from web_infra.infra.context.request_context_snapshot import RequestContextSnapshot

__all__ = [
    "RequestContext",
    "RequestContextSnapshot",
    "generate_trace_id",
    "ANONYMOUS_USER",
    "SYSTEM_USER",
]
