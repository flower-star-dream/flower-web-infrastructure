"""
统一向量化响应结构

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一向量化响应结构，屏蔽供应商差异（AI 规范 §2.2）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from web_infra.capabilities.ai.usage import Usage


class EmbeddingResponse(BaseModel):
    """统一向量化响应结构"""

    model: str = Field(default="", description="实际使用的模型名")
    embeddings: list[list[float]] = Field(default_factory=list, description="向量列表")
    usage: Usage = Field(default_factory=Usage, description="Token 用量")
