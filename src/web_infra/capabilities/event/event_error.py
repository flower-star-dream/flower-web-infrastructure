"""
事件总线错误码

@Author: 花海
@Date: 2026/08/22 17:00
@Description: 事件总线错误码（接入框架错误码体系）：监听器异常隔离、注册冲突等。
"""
from __future__ import annotations

import logging

from web_infra.infra.error.error_code import ErrorCode


class EventErrorCode:
    """事件总线错误码（规范 §4 格式：E<大类>-<子类>-<3位编号>；E4=请求/业务类，http_status=422；
    大类写在 category 字段（ErrorCode 的 category 指 E1..E5 前缀），与 parse_category 兼容。
    落地时若认为监听器异常更贴近基础设施类，可改用 E3-EVNT-xxx（500），此处选 E4 业务域）"""

    LISTENER_NOT_FOUND = ErrorCode(
        code="E4-EVNT-200", message="事件监听器未注册", http_status=422, category="E4", log_level=logging.WARNING
    )
    REGISTER_CONFLICT = ErrorCode(
        code="E4-EVNT-201", message="事件监听器重复注册", http_status=422, category="E4", log_level=logging.WARNING
    )
