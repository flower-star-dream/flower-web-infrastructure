"""
请求上下文快照

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 请求上下文快照结构，用于跨线程/异步任务显式传递上下文（规范 §16.4 / §17.4）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RequestContextSnapshot:
    """请求上下文快照，用于跨线程/异步任务显式传递上下文（规范 §16.4 / §17.4）"""

    trace_id: str = ""
    user_id: str = ""
    scope: str = ""
    client_id: str = ""
    service_id: str = ""
    tenant_id: str = ""
