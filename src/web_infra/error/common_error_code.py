"""
通用错误码

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 通用错误码定义（规范 §4.2.2 通用错误码参考表 + §6.8 认证错误码）。
              权威定义见 CommonErrorCodeEnum（error_code_enum.py），本类属性引用枚举成员值
              以保持对外 API 兼容（CommonErrorCode.SUCCESS.code 等引用方式不变）。
"""
from __future__ import annotations

from web_infra.error.error_code import ErrorCode
from web_infra.error.error_code_enum import CommonErrorCodeEnum
from web_infra.error.error_code_registry import ErrorCodeRegistry


class CommonErrorCode:
    """通用错误码定义（规范 §4.2.2 通用错误码参考表 + §6.8 认证错误码）——属性为枚举成员值，权威定义见 CommonErrorCodeEnum"""

    SUCCESS: ErrorCode = CommonErrorCodeEnum.SUCCESS.value

    SYS_UNKNOWN: ErrorCode = CommonErrorCodeEnum.SYS_UNKNOWN.value
    SYS_INTERNAL: ErrorCode = CommonErrorCodeEnum.SYS_INTERNAL.value
    SYS_UNAVAILABLE: ErrorCode = CommonErrorCodeEnum.SYS_UNAVAILABLE.value

    PARAM_INVALID: ErrorCode = CommonErrorCodeEnum.PARAM_INVALID.value
    PARAM_REQUIRED: ErrorCode = CommonErrorCodeEnum.PARAM_REQUIRED.value
    HTTP_METHOD_NOT_ALLOWED: ErrorCode = CommonErrorCodeEnum.HTTP_METHOD_NOT_ALLOWED.value
    RATE_LIMITED: ErrorCode = CommonErrorCodeEnum.RATE_LIMITED.value

    AUTH_UNAUTHENTICATED: ErrorCode = CommonErrorCodeEnum.AUTH_UNAUTHENTICATED.value
    AUTH_EXPIRED: ErrorCode = CommonErrorCodeEnum.AUTH_EXPIRED.value
    AUTH_INVALID: ErrorCode = CommonErrorCodeEnum.AUTH_INVALID.value
    AUTH_REFRESH_REQUIRED: ErrorCode = CommonErrorCodeEnum.AUTH_REFRESH_REQUIRED.value
    AUTH_KICKED: ErrorCode = CommonErrorCodeEnum.AUTH_KICKED.value
    PERM_DENIED: ErrorCode = CommonErrorCodeEnum.PERM_DENIED.value

    COMMON_NOT_FOUND: ErrorCode = CommonErrorCodeEnum.COMMON_NOT_FOUND.value
    COMMON_CONFLICT: ErrorCode = CommonErrorCodeEnum.COMMON_CONFLICT.value

    LOCK_FAILED: ErrorCode = CommonErrorCodeEnum.LOCK_FAILED.value


def _register_common_codes() -> None:
    """将通用错误码登记到注册表（遍历枚举注册，模块导入时执行一次，不再依赖 dir() 反射）"""
    for member in CommonErrorCodeEnum:
        ErrorCodeRegistry.register(member.value)


# 模块导入时登记通用错误码
_register_common_codes()
