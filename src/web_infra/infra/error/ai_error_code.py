"""
AI 错误码

@Author: 花海
@Date: 2026/08/14 10:00
@Description: AI 与大模型扩展错误码定义（原 web_infra.capabilities.ai.errors 迁移至此统一管理），遵循 AI 规范 §12。
              E3-THIRD 复用第三方调用子类；E4-AI 为 AI 特有业务域错误。
              权威定义见 AiErrorCodeEnum（error_code_enum.py），本类属性引用枚举成员值
              以保持对外 API 兼容（AiErrorCode.AI_NOT_CONFIGURED.code 等引用方式不变）。
"""
from __future__ import annotations

from web_infra.infra.error.error_code import ErrorCode
from web_infra.infra.error.error_code_enum import AiErrorCodeEnum
from web_infra.infra.error.error_code_registry import ErrorCodeRegistry


class AiErrorCode:
    """AI 特有错误码（AI 规范 §12）——属性为枚举成员值，权威定义见 AiErrorCodeEnum"""

    # E3-THIRD 第三方调用（可重试）
    THIRD_UNAVAILABLE: ErrorCode = AiErrorCodeEnum.THIRD_UNAVAILABLE.value
    THIRD_TIMEOUT: ErrorCode = AiErrorCodeEnum.THIRD_TIMEOUT.value
    THIRD_RATE_LIMITED: ErrorCode = AiErrorCodeEnum.THIRD_RATE_LIMITED.value
    THIRD_RAG_FAILED: ErrorCode = AiErrorCodeEnum.THIRD_RAG_FAILED.value

    # E4-AI 业务域（不可重试）
    AI_NOT_CONFIGURED: ErrorCode = AiErrorCodeEnum.AI_NOT_CONFIGURED.value
    AI_CONTENT_REJECTED: ErrorCode = AiErrorCodeEnum.AI_CONTENT_REJECTED.value
    AI_CONTEXT_EXCEEDED: ErrorCode = AiErrorCodeEnum.AI_CONTEXT_EXCEEDED.value
    AI_GENERATION_FAILED: ErrorCode = AiErrorCodeEnum.AI_GENERATION_FAILED.value
    AI_QUOTA_EXHAUSTED: ErrorCode = AiErrorCodeEnum.AI_QUOTA_EXHAUSTED.value
    AI_RESOURCE_EXTENSION_MISSING: ErrorCode = AiErrorCodeEnum.AI_RESOURCE_EXTENSION_MISSING.value


def _register_ai_codes() -> None:
    """将 AI 错误码登记到注册表（遍历枚举注册，模块导入时执行一次，不再依赖 dir() 反射）"""
    for member in AiErrorCodeEnum:
        ErrorCodeRegistry.register(member.value)


# 模块导入时登记 AI 错误码
_register_ai_codes()
