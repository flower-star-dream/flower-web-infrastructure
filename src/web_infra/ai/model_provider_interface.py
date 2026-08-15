"""
模型供应商接口（Provider SPI）

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 模型供应商统一抽象接口，遵循 AI 规范 §2.1 / §2.2。
              业务代码只依赖抽象接口与统一出入参结构，供应商 SDK 类型不向上泄漏。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from web_infra.ai.chat_request import ChatRequest
from web_infra.ai.chat_response import ChatResponse
from web_infra.ai.chat_stream_chunk import ChatStreamChunk
from web_infra.ai.embedding_request import EmbeddingRequest
from web_infra.ai.embedding_response import EmbeddingResponse


class ModelProviderInterface(ABC):
    """模型供应商抽象接口：定义模型能力，供应商实现类承载差异（AI 规范 §2.1）"""

    # 供应商逻辑名（唯一标识，如 openai / anthropic / deepseek）
    name: str = ""

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """对话生成（非流式）"""

    def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatStreamChunk]:
        """流式对话生成（默认不支持，供应商以 async generator 覆写实现，AI 规范 §9）"""
        raise NotImplementedError(f"供应商 {self.name} 不支持流式输出")

    async def embedding(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """向量化（默认不支持，供应商可覆盖实现）"""
        raise NotImplementedError(f"供应商 {self.name} 不支持向量化")
