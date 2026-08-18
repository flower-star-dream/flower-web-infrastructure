"""
向量检索命中结果

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 向量检索命中项（AI 规范 §11）：向量 ID + 相似度得分 + 向量本身。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class VectorHit(BaseModel):
    """向量检索命中项"""

    id: str = Field(description="向量唯一标识（如知识库文档块 ID）")
    score: float = Field(description="相似度得分（越大越相似）")
    vector: list[float] = Field(default_factory=list, description="向量值")
