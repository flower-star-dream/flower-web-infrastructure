"""
基础设施异常基类

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 定义基础设施异常基类，携带错误码，供全局异常处理统一拦截（规范 §4.7）。
"""
from __future__ import annotations

from typing import Any

from web_infra.error.error_code import ErrorCode


class WebInfraException(Exception):
    """基础设施异常基类：携带错误码，供全局异常处理统一拦截"""

    def __init__(self, error_code: ErrorCode, message: str | None = None, data: Any = None) -> None:
        self.error_code = error_code
        self.message = message or error_code.message
        self.data = data
        super().__init__(self.message)

    @property
    def code(self) -> str:
        """返回错误码字符串"""
        return self.error_code.code

    @property
    def http_status(self) -> int:
        """返回对应 HTTP 状态码"""
        return self.error_code.http_status
