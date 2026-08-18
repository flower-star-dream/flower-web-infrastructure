"""
统一流式分片结构

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一流式分片结构（AI 规范 §9：delta/finish_reason/usage）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from web_infra.capabilities.ai.finish_reason_enum import FinishReason
from web_infra.capabilities.ai.usage import Usage


class ChatStreamChunk(BaseModel):
    """统一流式分片结构（AI 规范 §9：delta/finish_reason/usage）"""

    delta: str = Field(default="", description="增量内容片段")
    finish_reason: FinishReason | None = Field(default=None, description="结束原因（流结束时有值）")
    usage: Usage | None = Field(default=None, description="Token 用量（结束时返回）")
    # AI-5：流开始后异常通过统一流内错误分片终止并携带错误码（如 E3-THIRD-001/E4-AI-004）；
    # 正常分片为 None，错误终止分片携带错误码且 finish_reason=ERROR
    error: str | None = Field(default=None, description="AI-5 错误分片：流开始后异常的错误码（正常分片为 None）")
