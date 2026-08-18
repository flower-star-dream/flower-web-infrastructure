"""
OpenAI 兼容协议供应商包

@Author: 花海
@Date: 2026/08/14 23:30
@Description: AI 规范 §17.4 默认协议（OpenAI 兼容格式 /v1/chat/completions）实现，供模型自动注册使用。
"""
from web_infra.capabilities.ai.provider.openai_compatible_provider import OpenAICompatibleProvider

__all__ = ["OpenAICompatibleProvider"]
