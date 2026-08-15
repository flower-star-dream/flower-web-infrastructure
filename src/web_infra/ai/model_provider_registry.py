"""
模型供应商注册表

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 模型供应商注册表：显式注册供应商与模型清单（AI 规范 §2.1 注册方式）。
"""
from __future__ import annotations

from typing import ClassVar

from web_infra.ai.model_provider_interface import ModelProviderInterface
from web_infra.error.ai_error_code import AiErrorCode
from web_infra.error.biz_exception import BizException


class ModelProviderRegistry:
    """模型供应商注册表：显式注册供应商与模型清单（AI 规范 §2.1 注册方式）"""

    _providers: ClassVar[dict[str, ModelProviderInterface]] = {}

    @classmethod
    def register(cls, provider: ModelProviderInterface) -> ModelProviderInterface:
        """注册一个模型供应商，返回该供应商"""
        cls._providers[provider.name] = provider
        return provider

    @classmethod
    def get(cls, name: str) -> ModelProviderInterface:
        """按逻辑名获取供应商；未配置时快速失败并抛出 E4-AI-001（AI 规范 §2.1）"""
        provider = cls._providers.get(name)
        if provider is None:
            raise BizException(AiErrorCode.AI_NOT_CONFIGURED, message=f"模型供应商未配置：{name}")
        return provider

    @classmethod
    def contains(cls, name: str) -> bool:
        """判断供应商是否已注册"""
        return name in cls._providers

    @classmethod
    def names(cls) -> list[str]:
        """返回已注册供应商逻辑名列表"""
        return list(cls._providers.keys())
