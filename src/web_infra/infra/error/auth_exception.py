"""
认证异常

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 认证异常：用于未认证/凭证过期等场景（E2-AUTH，401）。
"""
from __future__ import annotations

from web_infra.infra.error.common_error_code import CommonErrorCode
from web_infra.infra.error.error_code import ErrorCode
from web_infra.infra.error.web_infra_exception import WebInfraException


class AuthException(WebInfraException):
    """认证异常：用于未认证/凭证过期等场景（E2-AUTH，401）"""

    def __init__(
        self,
        error_code: ErrorCode = CommonErrorCode.AUTH_UNAUTHENTICATED,
        message: str | None = None,
    ) -> None:
        super().__init__(error_code, message=message)
