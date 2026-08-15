"""
AI 扩展小项单元测试（SSE 错误分片 / E4-AI-006 / ChatRequest 超时字段）

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 验证流内错误分片格式（AI 规范 §10）、E4-AI-006 注册（§13）与 TTFT/全量超时字段（§4.1）。
"""
from web_infra.ai import ChatRequest
from web_infra.error import AiErrorCode
from web_infra.error.error_code_registry import ErrorCodeRegistry
from web_infra.web import format_sse_error


def test_format_sse_error_frame():
    """流内错误分片：event: error + data 含 code/message"""
    frame = format_sse_error("E4-AI-002", "输出内容未通过安全审核")
    assert frame.startswith("event: error\n")
    assert 'data: {"code":"E4-AI-002","message":"输出内容未通过安全审核"}' in frame
    assert frame.endswith("\n\n")


def test_ai_error_code_006_registered():
    """E4-AI-006 已定义并注册（AI 规范 §13）"""
    assert AiErrorCode.AI_RESOURCE_EXTENSION_MISSING.code == "E4-AI-006"
    assert ErrorCodeRegistry.get("E4-AI-006") is not None


def test_chat_request_timeout_fields():
    """ChatRequest 支持 TTFT/全量超时字段（AI 规范 §4.1）"""
    request = ChatRequest(
        model="deepseek",
        messages=[],
        ttft_timeout_seconds=5.0,
        total_timeout_seconds=60.0,
    )
    assert request.ttft_timeout_seconds == 5.0
    assert request.total_timeout_seconds == 60.0
    # 默认 None（由网关配置兜底）
    default = ChatRequest(model="deepseek", messages=[])
    assert default.ttft_timeout_seconds is None
    assert default.total_timeout_seconds is None
