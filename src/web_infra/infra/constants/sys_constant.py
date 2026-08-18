"""
系统域常量（SYS_ 前缀）

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 系统级常量（日志级别、错误码大类、匿名占位符等），对应错误码大类 E5。
"""
from __future__ import annotations


class SysConstant:
    """系统域常量类（规范 §5.2 / §5.3）"""

    SYS_LOG_LEVEL_ERROR = "error"
    SYS_LOG_LEVEL_WARNING = "warning"
    SYS_LOG_LEVEL_INFO = "info"

    SYS_ERROR_CATEGORY_PARAM = "E1"
    SYS_ERROR_CATEGORY_AUTH = "E2"
    SYS_ERROR_CATEGORY_INFRA = "E3"
    SYS_ERROR_CATEGORY_BIZ = "E4"
    SYS_ERROR_CATEGORY_SYSTEM = "E5"
    SYS_ERROR_CATEGORY_SUCCESS = "S"

    # 统一成功码（规范 §4.1）：Result 与 CommonErrorCode 均引用此单一来源
    SYS_SUCCESS_CODE = "S0000"
    SYS_SUCCESS_MESSAGE = "ok"

    SYS_ANONYMOUS_USER = "anonymous"
    SYS_SYSTEM_USER = "system"
    SYS_LOG_UNKNOWN_HEADER = "-"
    SYS_SLOW_REQUEST_THRESHOLD_MS = 5000
    SYS_DEFAULT_SERVICE_NAME = "app"
