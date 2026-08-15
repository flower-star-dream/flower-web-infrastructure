"""
权限异常

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 权限异常：用于无权限场景（E2-PERM，403）。
"""
from __future__ import annotations

from web_infra.error.common_error_code import CommonErrorCode
from web_infra.error.error_code import ErrorCode
from web_infra.error.web_infra_exception import WebInfraException


class PermException(WebInfraException):
    """权限异常：用于无权限场景（E2-PERM，403）"""

    def __init__(
        self,
        message: str | None = None,
        error_code: ErrorCode = CommonErrorCode.PERM_DENIED,
    ) -> None:
        super().__init__(error_code, message=message)
