"""
向量嵌入接口

@Author: 花海
@Date: 2026/08/14 15:00
@Description: Embedding 供应商抽象（AI 规范 §11），业务接入 bge-m3 / OpenAI 等模型时实现该接口。
              默认实现：HashEmbeddingProvider（web_infra.capabilities.ai.retrieval.hash_embedding_provider，
              规范 S3-1 扩展点必须提供默认实现）——仅保证同文本向量稳定可比较，用于本地检索/降级兜底，
              生产环境应注入真实模型供应商。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProviderInterface(ABC):
    """向量嵌入供应商接口"""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """将单段文本转为向量"""
        raise NotImplementedError

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量将文本转为向量（顺序与入参一致）"""
        raise NotImplementedError
