"""
业务异常

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 业务异常：用于业务规则冲突、资源不存在等业务域错误（默认 E4 大类）。
"""
from __future__ import annotations

from typing import Any

from web_infra.infra.error.common_error_code import CommonErrorCode
from web_infra.infra.error.error_code import ErrorCode
from web_infra.infra.error.web_infra_exception import WebInfraException


class BizException(WebInfraException):
    """业务异常：用于业务规则冲突、资源不存在等业务域错误（默认 E4 大类）。

    统一抛出约定：业务代码经 `错误码.to_exception(message=...)` 抛出（见 ErrorCode.to_exception），
    避免散落本构造函数；域专属异常（ParamException / PermException / AuthException）仍用对应构造函数。
    """

    def __init__(
        self,
        error_code: ErrorCode = CommonErrorCode.COMMON_CONFLICT,
        message: str | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(error_code, message=message, data=data)
