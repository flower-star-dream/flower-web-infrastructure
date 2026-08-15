"""
统一向量化请求结构

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一向量化请求结构，屏蔽供应商差异（AI 规范 §2.2）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class EmbeddingRequest(BaseModel):
    """统一向量化请求结构"""

    model: str = Field(description="Embedding 模型逻辑名")
    input: str | list[str] = Field(description="待向量化文本")
