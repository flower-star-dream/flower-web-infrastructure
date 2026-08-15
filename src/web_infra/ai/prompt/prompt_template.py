"""
提示词模板数据模型

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 提示词模板模型（AI 规范 §6.1：模板集中管理、版本化），
              含唯一键、版本号与模板内容，供 PromptTemplateStore 存取。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PromptTemplate(BaseModel):
    """提示词模板：key + 版本 + 内容"""

    key: str = Field(description="模板唯一键（如 report.comprehensive）")
    version: str = Field(default="1.0.0", description="模板版本号（版本变更应同步失效 AI 缓存）")
    content: str = Field(description="模板内容，占位符使用 {var} 风格")
    description: str = Field(default="", description="模板说明")

    @property
    def fingerprint(self) -> str:
        """模板指纹：key + version，用于标识同一版本模板（AI 缓存 Key 组成要素）"""
        return f"{self.key}:{self.version}"
