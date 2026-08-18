"""
统一消息结构

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一消息结构，屏蔽供应商差异（AI 规范 §2.2）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from web_infra.capabilities.ai.chat_role_enum import ChatRole


class ChatMessage(BaseModel):
    """统一消息结构"""

    role: ChatRole = Field(description="消息角色")
    content: str = Field(default="", description="消息内容")
