"""
文档切片接口

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 文档切片器抽象（AI 规范 §11），按文档类型提供实现（默认 Markdown）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from web_infra.ai.retrieval.chunk import Chunk


class DocumentChunkerInterface(ABC):
    """文档切片器接口"""

    @abstractmethod
    def chunk(self, document: str) -> list[Chunk]:
        """将文档切分为有序切片列表（切片携带标题上下文，原子块不拆分）"""
        raise NotImplementedError
