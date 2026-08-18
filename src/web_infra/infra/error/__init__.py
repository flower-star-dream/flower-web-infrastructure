"""
错误码与异常模块

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 导出错误码、异常与全局异常处理相关能力，遵循规范 §4。
"""
from web_infra.infra.error.error_code import (
    ErrorCode,
    parse_category,
    derive_http_status,
    is_client_error,
    is_retryable,
    converge_error_code,
    CONVERGED_MESSAGES,
    PASS_CATEGORIES,
    HIDE_CATEGORIES,
)
from web_infra.infra.error.error_code_registry import ErrorCodeRegistry
from web_infra.infra.error.error_code_enum import CommonErrorCodeEnum, AiErrorCodeEnum
from web_infra.infra.error.common_error_code import CommonErrorCode
from web_infra.infra.error.ai_error_code import AiErrorCode
from web_infra.infra.error.web_infra_exception import WebInfraException
from web_infra.infra.error.biz_exception import BizException
from web_infra.infra.error.param_exception import ParamException
from web_infra.infra.error.perm_exception import PermException
from web_infra.infra.error.auth_exception import AuthException
from web_infra.infra.error.handler import register_global_exception_handlers

__all__ = [
    "ErrorCode",
    "ErrorCodeRegistry",
    "CommonErrorCode",
    "AiErrorCode",
    "CommonErrorCodeEnum",
    "AiErrorCodeEnum",
    "parse_category",
    "derive_http_status",
    "is_client_error",
    "is_retryable",
    "converge_error_code",
    "CONVERGED_MESSAGES",
    "PASS_CATEGORIES",
    "HIDE_CATEGORIES",
    "WebInfraException",
    "BizException",
    "ParamException",
    "PermException",
    "AuthException",
    "register_global_exception_handlers",
]
