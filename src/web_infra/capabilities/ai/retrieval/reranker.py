"""
Rerank 接口

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 检索结果重排抽象（AI 规范 §11：Rerank 提升检索精度），
              默认原样返回（IdentityReranker），可接入 CrossEncoder 等模型实现。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class RerankerInterface(ABC):
    """重排器接口"""

    @abstractmethod
    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """对文档列表按 query 重排打分，返回与 documents 顺序一致的重排分数（越大越相关）"""
        raise NotImplementedError
