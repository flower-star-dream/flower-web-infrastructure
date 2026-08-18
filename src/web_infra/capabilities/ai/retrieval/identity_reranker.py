"""
原样重排器

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 不做重排（Identity），返回 1.0 平分（默认实现），
              配合 Retriever 保持向量库原始排序。
"""
from __future__ import annotations

from web_infra.capabilities.ai.retrieval.reranker import RerankerInterface


class IdentityReranker(RerankerInterface):
    """原样重排器（默认实现）：全部返回 1.0，不改变原有排序"""

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [1.0] * len(documents)
