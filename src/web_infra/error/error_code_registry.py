"""
错误码注册表

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 错误码注册表：集中登记错误码，提供统一解析入口（规范 §4.3）。
"""
from __future__ import annotations

from typing import ClassVar

from web_infra.error.error_code import (
    ErrorCode,
    derive_http_status,
    derive_log_level,
    is_retryable,
    parse_category,
)


class ErrorCodeRegistry:
    """错误码注册表：集中登记错误码，提供统一解析入口（规范 §4.3）"""

    _codes: ClassVar[dict[str, ErrorCode]] = {}

    @classmethod
    def register(cls, error_code: ErrorCode) -> ErrorCode:
        """注册一个错误码，返回该错误码"""
        cls._codes[error_code.code] = error_code
        return error_code

    @classmethod
    def get(cls, code: str) -> ErrorCode | None:
        """按 code 精确查询已注册错误码，未注册返回 None"""
        return cls._codes.get(code)

    @classmethod
    def parse(cls, code: str) -> ErrorCode:
        """统一解析入口：优先返回已注册错误码，否则按大类推导一个临时定义（规范 §4.3）"""
        registered = cls.get(code)
        if registered is not None:
            return registered
        category = parse_category(code)
        return ErrorCode(
            code=code,
            message="",
            http_status=derive_http_status(code),
            category=category,
            retryable=is_retryable(category),
            log_level=derive_log_level(category),
        )
