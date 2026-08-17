"""
错误码枚举

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 用 enum.Enum 承载通用/AI 错误码枚举（规范 §5.5 风格），成员值为 ErrorCode 结构载体。
              CommonErrorCodeEnum / AiErrorCodeEnum 为错误码的权威定义；
              CommonErrorCode / AiErrorCode 类属性引用枚举成员值以保持对外 API 兼容；
              注册表遍历枚举注册（不再依赖 dir() 反射，见 common_error_code.py / ai_error_code.py）。
"""
from __future__ import annotations

import logging
from enum import Enum

from web_infra.constants.sys_constant import SysConstant
from web_infra.error.error_code import ErrorCode


class CommonErrorCodeEnum(Enum):
    """通用错误码枚举（规范 §4.2.2 通用错误码参考表 + §6.8 认证错误码）"""

    SUCCESS = ErrorCode(SysConstant.SYS_SUCCESS_CODE, SysConstant.SYS_SUCCESS_MESSAGE, 200, "S")

    SYS_UNKNOWN = ErrorCode("E5-SYS-000", "系统未知异常", 500, "E5", log_level=logging.ERROR)
    SYS_INTERNAL = ErrorCode("E5-SYS-001", "通用服务器错误", 500, "E5", log_level=logging.ERROR)
    SYS_UNAVAILABLE = ErrorCode("E5-SYS-002", "服务不可用", 503, "E5", log_level=logging.ERROR)

    PARAM_INVALID = ErrorCode("E1-PARAM-000", "参数错误", 400, "E1")
    PARAM_REQUIRED = ErrorCode("E1-PARAM-001", "查询参数不能为空", 400, "E1")
    HTTP_METHOD_NOT_ALLOWED = ErrorCode("E1-HTTP-000", "方法不允许", 405, "E1")
    RATE_LIMITED = ErrorCode("E1-RATE-000", "请求过于频繁", 429, "E1")

    AUTH_UNAUTHENTICATED = ErrorCode("E2-AUTH-000", "未认证", 401, "E2")
    AUTH_EXPIRED = ErrorCode("E2-AUTH-001", "凭证已过期", 401, "E2")
    AUTH_INVALID = ErrorCode("E2-AUTH-002", "凭证非法/签名错误", 401, "E2")
    AUTH_REFRESH_REQUIRED = ErrorCode("E2-AUTH-003", "凭证即将过期", 401, "E2")
    AUTH_KICKED = ErrorCode("E2-AUTH-004", "单点登录被踢", 401, "E2")
    PERM_DENIED = ErrorCode("E2-PERM-000", "无权限", 403, "E2")
    AUTH_SOCIAL_PLATFORM_NOT_CONFIGURED = ErrorCode("E2-AUTH-005", "三方登录平台未注册/未配置", 422, "E2")
    AUTH_SOCIAL_TOKEN_FAILED = ErrorCode("E2-AUTH-006", "三方授权码无效或换取凭证失败", 422, "E2")
    AUTH_SOCIAL_NOT_BOUND = ErrorCode("E2-AUTH-007", "三方账号未绑定本地用户", 422, "E2")
    AUTH_SOCIAL_ALREADY_BOUND = ErrorCode("E2-AUTH-008", "三方账号已被其他用户绑定", 409, "E2")

    COMMON_NOT_FOUND = ErrorCode("E4-COMMON-000", "资源不存在", 404, "E4", log_level=logging.WARNING)
    COMMON_CONFLICT = ErrorCode("E4-COMMON-001", "资源冲突", 409, "E4", log_level=logging.WARNING)

    LOCK_FAILED = ErrorCode("E3-LOCK-000", "锁获取失败", 423, "E3", retryable=True, log_level=logging.ERROR)

    @classmethod
    def of(cls, code: str) -> CommonErrorCodeEnum | None:
        """按 code 反查枚举成员；未找到返回 None"""
        for member in cls:
            if member.value.code == code:
                return member
        return None


class AiErrorCodeEnum(Enum):
    """AI 特有错误码枚举（AI 规范 §12）"""

    # E3-THIRD 第三方调用（可重试）
    THIRD_UNAVAILABLE = ErrorCode("E3-THIRD-001", "模型供应商服务不可用", 500, "E3", retryable=True, log_level=logging.ERROR)
    THIRD_TIMEOUT = ErrorCode("E3-THIRD-002", "模型供应商调用超时", 500, "E3", retryable=True, log_level=logging.ERROR)
    THIRD_RATE_LIMITED = ErrorCode("E3-THIRD-003", "模型供应商限流", 500, "E3", retryable=True, log_level=logging.WARNING)
    THIRD_RAG_FAILED = ErrorCode("E3-THIRD-004", "RAG 检索失败/知识库不可用", 500, "E3", retryable=True, log_level=logging.ERROR)

    # E4-AI 业务域（不可重试）
    AI_NOT_CONFIGURED = ErrorCode("E4-AI-001", "模型/供应商未配置或不存在", 422, "E4", log_level=logging.WARNING)
    AI_CONTENT_REJECTED = ErrorCode("E4-AI-002", "输出内容未通过安全审核", 422, "E4", log_level=logging.WARNING)
    AI_CONTEXT_EXCEEDED = ErrorCode("E4-AI-003", "输入超过上下文/Token 上限", 422, "E4", log_level=logging.WARNING)
    AI_GENERATION_FAILED = ErrorCode("E4-AI-004", "模型生成失败", 422, "E4", log_level=logging.WARNING)
    AI_QUOTA_EXHAUSTED = ErrorCode("E4-AI-005", "成本配额已耗尽", 422, "E4", log_level=logging.WARNING)
    AI_RESOURCE_EXTENSION_MISSING = ErrorCode("E4-AI-006", "资源管理扩展点未配置/未实现", 422, "E4", log_level=logging.WARNING)

    @classmethod
    def of(cls, code: str) -> AiErrorCodeEnum | None:
        """按 code 反查枚举成员；未找到返回 None"""
        for member in cls:
            if member.value.code == code:
                return member
        return None
