"""
日志上下文过滤器

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 日志上下文过滤器：将 TraceId / 用户 ID / 阶段注入日志记录。
"""
from __future__ import annotations

import logging

from web_infra.infra.context import RequestContext


class ContextFilter(logging.Filter):
    """日志上下文过滤器：将 TraceId / 用户 ID / 阶段注入日志记录"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = RequestContext.get_trace_id() or "-"
        record.user_id = RequestContext.get_user_id() or "-"
        record.phase = getattr(record, "phase", "-")
        return True
