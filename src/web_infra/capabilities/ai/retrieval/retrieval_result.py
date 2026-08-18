"""
检索结果模型

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 检索结果（AI 规范 §11）：文档 ID + 文本 + 相似度得分。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RetrievalResult(BaseModel):
    """检索结果"""

    id: str = Field(description="文档/切片 ID")
    text: str = Field(description="检索命中的文本")
    score: float = Field(default=0.0, description="相似度得分（越大越相关）")
