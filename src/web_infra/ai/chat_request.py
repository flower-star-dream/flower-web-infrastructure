"""
统一对话请求结构

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一对话请求结构，屏蔽供应商差异（AI 规范 §2.2）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from web_infra.ai.chat_message import ChatMessage


class ChatRequest(BaseModel):
    """统一对话请求结构"""

    model: str = Field(description="模型逻辑名（业务代码只引用逻辑名，见 AI 规范 §3.2）")
    messages: list[ChatMessage] = Field(description="消息列表（含系统提示词与历史会话）")
    temperature: float | None = Field(default=None, description="采样温度")
    max_tokens: int | None = Field(default=None, description="最大输出 Token 数")
    stream: bool = Field(default=False, description="是否流式输出")
    model_version: str | None = Field(default=None, description="模型版本（AI 规范 §8：参与缓存 Key，版本变更缓存自然失效）")
    idempotency_key: str | None = Field(default=None, description="幂等键（AI 规范 §4.2）")
    ttft_timeout_seconds: float | None = Field(default=None, description="首 Token（TTFT）超时（秒，AI 规范 §4.1 流式场景）")
    total_timeout_seconds: float | None = Field(default=None, description="全量生成超时（秒，AI 规范 §4.1）")
