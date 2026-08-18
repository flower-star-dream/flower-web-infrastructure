"""
Token 用量

@Author: 花海
@Date: 2026/08/14 10:00
@Description: Token 用量结构（AI 规范 §14 成本计量）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Usage(BaseModel):
    """Token 用量（AI 规范 §14 成本计量）"""

    prompt_tokens: int = Field(default=0, description="输入 Token 数")
    completion_tokens: int = Field(default=0, description="输出 Token 数")
    total_tokens: int = Field(default=0, description="总 Token 数")
