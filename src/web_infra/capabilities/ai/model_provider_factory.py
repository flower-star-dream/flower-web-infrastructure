"""
模型供应商工厂

@Author: 花海
@Date: 2026/08/14 23:30
@Description: 模型供应商协议构建器（AI 规范 §17.4/§2.1）：
              按 ModelConfig.provider 字段构建对应供应商实例；
              未注册的自定义协议一律回落 OpenAI 兼容格式（默认协议），
              私有化/自定义供应商经 register_factory 注册后由配置自动装配。
"""
from __future__ import annotations

from typing import Callable, ClassVar

from web_infra.capabilities.ai.model_config import ModelConfig
from web_infra.capabilities.ai.model_provider_interface import ModelProviderInterface
from web_infra.capabilities.ai.provider.openai_compatible_provider import OpenAICompatibleProvider


class ModelProviderFactory:
    """模型供应商协议构建器：provider 字段 -> 供应商实例（未注册协议回落 OpenAI 兼容）"""

    _factories: ClassVar[dict[str, Callable[[ModelConfig], ModelProviderInterface]]] = {}

    @classmethod
    def register_factory(cls, provider_type: str, factory: Callable[[ModelConfig], ModelProviderInterface]) -> None:
        """注册自定义供应商构建器（供应商 SPI 接入点，AI 规范 §2.1）。

        :param provider_type: 供应商逻辑名（与 ModelConfig.provider 字段匹配）
        :param factory: 按 ModelConfig 构建供应商实例的工厂函数
        """
        cls._factories[provider_type] = factory

    @classmethod
    def create(cls, config: ModelConfig) -> ModelProviderInterface:
        """按模型配置构建供应商实例。

        :param config: 标准化模型配置
        :return: 供应商实例（已注册的自定义协议优先；否则 OpenAI 兼容默认协议）
        """
        factory = cls._factories.get(config.provider)
        if factory is not None:
            return factory(config)
        return OpenAICompatibleProvider(config)
