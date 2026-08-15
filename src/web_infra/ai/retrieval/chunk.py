"""
文档切片数据模型

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 文档切片（Chunk）模型（AI 规范 §11：知识源切片入库），
              携带切片文本、所属标题上下文与顺序号。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    """文档切片：文本 + 标题上下文 + 顺序"""

    text: str = Field(description="切片文本")
    heading: str = Field(default="", description="所属最近标题（无标题为空）")
    level: int = Field(default=0, description="标题层级（0 表示无标题）")
    order: int = Field(default=0, description="切片在文档中的顺序号")
