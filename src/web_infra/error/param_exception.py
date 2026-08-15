"""
参数异常

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 参数异常：用于缺参、类型错误、校验失败等参数类错误（E1 大类）。
"""
from __future__ import annotations

from web_infra.error.common_error_code import CommonErrorCode
from web_infra.error.error_code import ErrorCode
from web_infra.error.web_infra_exception import WebInfraException


class ParamException(WebInfraException):
    """参数异常：用于缺参、类型错误、校验失败等参数类错误（E1 大类）"""

    def __init__(
        self,
        message: str | None = None,
        error_code: ErrorCode = CommonErrorCode.PARAM_INVALID,
    ) -> None:
        super().__init__(error_code, message=message)
