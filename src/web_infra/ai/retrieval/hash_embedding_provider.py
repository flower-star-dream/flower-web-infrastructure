"""
哈希特征嵌入提供者

@Author: 花海
@Date: 2026/08/15 10:00
@Description: EmbeddingProviderInterface 的本地默认实现（规范 S3-1：扩展点必须提供默认实现）：
              基于稳定哈希的特征嵌入，不依赖外部模型服务，仅保证「同文本向量稳定可比较」，
              用于本地检索/降级兜底；生产环境应注入真实模型供应商（如 bge-m3 / OpenAI 兼容服务）。
              注意：本实现只具备确定性，不具备语义质量，不可用于语义相似度排序等场景。
"""
from __future__ import annotations

import math
import re
import zlib

from web_infra.ai.retrieval.embedding_provider import EmbeddingProviderInterface

#: token 切分规则：英文单词/数字/下划线按词，中文按单字
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


def _tokens(text: str) -> list[str]:
    """将文本切分为 token 列表（统一小写，保证确定性）。"""
    return _TOKEN_RE.findall(text.lower())


class HashEmbeddingProvider(EmbeddingProviderInterface):
    """哈希特征嵌入提供者（EmbeddingProviderInterface 默认实现）"""

    def __init__(self, dimension: int = 256) -> None:
        """初始化哈希特征嵌入提供者。

        :param dimension: 输出向量维度（默认 256），必须为正整数
        :raises ValueError: dimension 非正整数时抛出
        """
        if dimension < 1:
            raise ValueError(f"dimension 必须为正整数，当前为 {dimension}")
        self._dimension = dimension

    def embed(self, text: str) -> list[float]:
        """将单段文本转为定长向量（确定性哈希特征，L2 归一化）。

        实现细节：逐 token 计算 crc32 哈希，映射到 [0, dimension) 索引累加，
        并用哈希高位决定累加符号（避免所有 token 同号导致向量退化），最后 L2 归一化；
        空文本返回全 0 向量。

        :param text: 输入文本
        :return: 长度为 dimension 的浮点向量
        """
        vector = [0.0] * self._dimension
        for token in _tokens(text):
            crc = zlib.crc32(token.encode("utf-8"))
            idx = crc % self._dimension
            sign = 1.0 if (crc >> 16) & 1 else -1.0
            vector[idx] += sign
        return self._normalize(vector)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量将文本转为向量（顺序与入参一致）。

        :param texts: 文本列表
        :return: 与入参顺序一致的向量列表
        """
        return [self.embed(text) for text in texts]

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        """对向量做 L2 归一化；零向量（空文本）原样返回，保证值为有限数。"""
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]
