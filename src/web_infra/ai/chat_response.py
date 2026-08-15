"""
统一对话响应结构

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一对话响应结构，屏蔽供应商差异（AI 规范 §2.2）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from web_infra.ai.chat_message import ChatMessage
from web_infra.ai.chat_role_enum import ChatRole
from web_infra.ai.finish_reason_enum import FinishReason
from web_infra.ai.usage import Usage


class ChatResponse(BaseModel):
    """统一对话响应结构"""

    id: str = Field(default="", description="本次生成请求标识")
    model: str = Field(default="", description="实际使用的模型名")
    message: ChatMessage = Field(default_factory=lambda: ChatMessage(role=ChatRole.ASSISTANT, content=""), description="生成结果")
    finish_reason: FinishReason = Field(default=FinishReason.STOP, description="结束原因")
    usage: Usage = Field(default_factory=Usage, description="Token 用量")
