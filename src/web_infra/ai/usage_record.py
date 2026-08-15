"""
Token 用量记录模型

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 单次模型调用的 Token 用量与成本记录（AI 规范 §5.2/§14 成本计量）。
"""
from __future__ import annotations

import time

from pydantic import BaseModel, Field


class UsageRecord(BaseModel):
    """单次调用用量与成本记录"""

    timestamp: float = Field(default_factory=time.time, description="调用时间（unix 秒）")
    model_code: str = Field(description="模型编码")
    provider: str = Field(default="", description="供应商")
    tenant_id: str = Field(default="", description="租户标识")
    scene: str = Field(default="", description="调用场景（如 chat/rag/rewrite）")
    prompt_tokens: int = Field(default=0, description="输入 Token 数")
    completion_tokens: int = Field(default=0, description="输出 Token 数")
    total_tokens: int = Field(default=0, description="总 Token 数")
    cost: float = Field(default=0.0, description="本次调用成本（元）")
