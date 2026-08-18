"""
AI 模型供应商 SPI 单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证供应商注册表、快速失败与统一出入参结构（AI 规范 §2）。
"""
import pytest

from web_infra.capabilities.ai import (
    ModelProviderInterface,
    ModelProviderRegistry,
    ChatRole,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    FinishReason,
)
from web_infra.infra.error import BizException
from web_infra.infra.error.ai_error_code import AiErrorCode


class _FakeProvider(ModelProviderInterface):
    """测试用供应商实现"""

    name = "fake"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            id="resp-1",
            model=request.model,
            message=ChatMessage(role=ChatRole.ASSISTANT, content="hi"),
            finish_reason=FinishReason.STOP,
        )


@pytest.mark.asyncio
async def test_provider_register_and_get():
    """供应商注册与获取"""
    ModelProviderRegistry.register(_FakeProvider())
    assert ModelProviderRegistry.contains("fake")
    assert ModelProviderRegistry.get("fake").name == "fake"


def test_provider_not_configured_fail_fast():
    """未配置供应商时快速失败，返回 E4-AI-001"""
    with pytest.raises(BizException) as exc_info:
        ModelProviderRegistry.get("not-exist")
    assert exc_info.value.code == "E4-AI-001"


def test_ai_error_codes_defined():
    """AI 特有错误码已定义"""
    assert AiErrorCode.AI_NOT_CONFIGURED.code == "E4-AI-001"
    assert AiErrorCode.THIRD_UNAVAILABLE.code == "E3-THIRD-001"
    assert AiErrorCode.THIRD_UNAVAILABLE.retryable is True


def test_chat_request_structure():
    """统一出入参结构"""
    req = ChatRequest(model="deepseek-chat", messages=[ChatMessage(role=ChatRole.USER, content="hello")])
    assert req.model == "deepseek-chat"
    assert req.messages[0].role == ChatRole.USER
