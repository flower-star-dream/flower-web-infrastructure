"""
搜索引擎检索命中结果

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 全文搜索引擎命中项（搜索引擎接入计划 v0.2.0 §3.2）：
              文档 ID + 相关性得分 + 文档原文 + 可选高亮片段（字段名 → 片段列表）。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SearchHit(BaseModel):
    """搜索引擎命中项"""

    id: str = Field(description="文档唯一标识")
    score: float = Field(description="相关性得分（越大越相关）")
    source: dict[str, Any] = Field(default_factory=dict, description="文档内容（写入时的原始字段）")
    highlight: dict[str, list[str]] = Field(
        default_factory=dict, description="高亮片段（字段名 → 高亮片段列表；未开启高亮时为空字典）"
    )
