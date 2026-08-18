"""
AI 模型网关 P0 整改单元测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 覆盖四项 P0 整改（AI 规范 §4.1/§4.2/§5.1/§7.2/§8.2）：
              1) 连接池流式/非流式客户端注入供应商（§5.1 分池生效）；
              2) TTFT 首包超时与全量生成超时生效（挂起模拟，§4.1）；
              3) retryable 错误指数退避重试 + 幂等键自动生成复用，非 retryable 不重试（§4.2/§7.2）；
              4) 内容审核接入网关：输入/输出 BLOCK 抛 E4-AI-002，流式首片前拦截（§8.2）。
"""
import asyncio

import httpx
import pytest

from web_infra.capabilities.ai import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatRole,
    ChatStreamChunk,
    ConnectionPoolManager,
    FinishReason,
    ModelConfig,
    ModelGateway,
    ModelProviderInterface,
    ModelProviderRegistry,
    OpenAICompatibleProvider,
    RuleBasedContentGuard,
    Usage,
)
from web_infra.capabilities.ai.model_gateway import ModelRouter, RouteEntry
from web_infra.infra.error import BizException
from web_infra.infra.error.ai_error_code import AiErrorCode

API_BASE = "http://mock.test/v1"


def _config(**overrides) -> ModelConfig:
    """构造最小模型配置（model_id 缺省回落 model_code）"""
    base = dict(
        id=1,
        model_name="Mock Chat",
        model_code="mock-chat",
        provider="openai_compatible",
        api_base=API_BASE,
        api_key="sk-test",
        timeout=120,
    )
    base.update(overrides)
    return ModelConfig(**base)


def _request(model: str = "mock-chat", **overrides) -> ChatRequest:
    """构造最小对话请求"""
    base = dict(model=model, messages=[ChatMessage(role=ChatRole.USER, content="hello")])
    base.update(overrides)
    return ChatRequest(**base)


@pytest.fixture
def clean_registry():
    """测试后清理全局供应商注册表，避免污染其他用例"""
    before = dict(ModelProviderRegistry._providers)
    yield
    ModelProviderRegistry._providers.clear()
    ModelProviderRegistry._providers.update(before)


def _gateway(routes: dict[str, RouteEntry], *, pool_manager=None, content_guard=None, **kwargs) -> ModelGateway:
    """构造网关：路由 + 可选连接池/内容审核/重试参数"""
    return ModelGateway(
        ModelRouter(routes),
        pool_manager=pool_manager,
        content_guard=content_guard,
        **kwargs,
    )


# ------------------------------------------------------------------
# 整改 1：连接池客户端注入供应商（AI 规范 §5.1 流式/非流式分池）
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_clients_uses_stream_and_sync_pools():
    """attach_clients 后流式/非流式调用分别使用分池客户端（分池生效）"""
    provider = OpenAICompatibleProvider(_config())
    stream_client = httpx.AsyncClient()
    sync_client = httpx.AsyncClient()
    try:
        provider.attach_clients(stream_client=stream_client, sync_client=sync_client)
        assert provider._get_client(stream=True) is stream_client
        assert provider._get_client(stream=False) is sync_client
        assert stream_client is not sync_client
    finally:
        await stream_client.aclose()
        await sync_client.aclose()


@pytest.mark.asyncio
async def test_gateway_injects_pool_clients_to_provider(clean_registry):
    """网关在获取供应商时将连接池流式/非流式客户端注入（§5.1 分池生效）"""
    provider = OpenAICompatibleProvider(_config())
    provider.name = "mock-chat"
    ModelProviderRegistry.register(provider)
    pool = ConnectionPoolManager()
    try:
        gateway = _gateway({"chat": RouteEntry("mock-chat")}, pool_manager=pool)
        await gateway._attach_pool_clients(provider, "mock-chat")
        assert provider._get_client(stream=True) is await pool.get_stream_client()
        assert provider._get_client(stream=False) is await pool.get_sync_client()
        # 重复注入被去重（不重复创建连接池客户端）
        await gateway._attach_pool_clients(provider, "mock-chat")
        assert provider._get_client(stream=True) is await pool.get_stream_client()
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_attach_pool_clients_concurrent_single_injection(clean_registry):
    """并发首次注入：多个并发调用仅注入一次连接池客户端（H2 修复防重复创建）"""
    provider = OpenAICompatibleProvider(_config())
    provider.name = "mock-chat"
    attach_count = {"n": 0}
    original_attach = provider.attach_clients

    def counting_attach(**kwargs):
        attach_count["n"] += 1
        original_attach(**kwargs)

    provider.attach_clients = counting_attach
    ModelProviderRegistry.register(provider)
    pool = ConnectionPoolManager()
    try:
        gateway = _gateway({"chat": RouteEntry("mock-chat")}, pool_manager=pool)
        await asyncio.gather(*[gateway._attach_pool_clients(provider, "mock-chat") for _ in range(10)])
        assert attach_count["n"] == 1  # 仅注入一次，未重复创建连接池客户端
        assert provider._get_client(stream=True) is await pool.get_stream_client()
        assert provider._get_client(stream=False) is await pool.get_sync_client()
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_attach_clients_does_not_override_explicit_client():
    """构造注入的客户端（MockTransport 测试）优先于连接池客户端，保持向后兼容"""
    mock_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"id": "1", "choices": [{"message": {"content": "ok"}}]}))
    )
    stream_client = httpx.AsyncClient()
    sync_client = httpx.AsyncClient()
    provider = OpenAICompatibleProvider(_config(), client=mock_client)
    try:
        provider.attach_clients(stream_client=stream_client, sync_client=sync_client)
        assert provider._get_client(stream=True) is mock_client
        assert provider._get_client(stream=False) is mock_client
    finally:
        await mock_client.aclose()
        await stream_client.aclose()
        await sync_client.aclose()


# ------------------------------------------------------------------
# 整改 2：TTFT/全量超时生效（AI 规范 §4.1）
# ------------------------------------------------------------------


class HangingBody(httpx.AsyncByteStream):
    """响应体读取时挂起的流（模拟供应商首包迟迟不返回）"""

    async def __aiter__(self):
        await asyncio.sleep(60)
        yield b""

    async def aclose(self) -> None:
        pass


class PartialThenHangingBody(httpx.AsyncByteStream):
    """先输出一行 SSE 再挂起（模拟流式生成中途卡住）"""

    def __init__(self) -> None:
        self._sent_first = False

    async def __aiter__(self):
        if not self._sent_first:
            self._sent_first = True
            yield b'data: {"id":"1","choices":[{"delta":{"content":"hi"},"finish_reason":null}]}\n\n'
        await asyncio.sleep(60)
        yield b""

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
async def test_stream_ttft_timeout():
    """流式首分片超过 ttft_timeout_seconds：抛 E3-THIRD-002（TTFT 超时生效）"""
    provider = OpenAICompatibleProvider(
        _config(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=HangingBody()))),
    )
    with pytest.raises(BizException) as exc_info:
        async for _ in provider.stream_chat(_request(ttft_timeout_seconds=0.05)):
            pass
    assert exc_info.value.code == "E3-THIRD-002"


@pytest.mark.asyncio
async def test_chat_total_timeout():
    """非流式调用超过 total_timeout_seconds：抛 E3-THIRD-002（全量超时生效）"""

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(60)
        return httpx.Response(200, json={})

    provider = OpenAICompatibleProvider(
        _config(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(BizException) as exc_info:
        await provider.chat(_request(total_timeout_seconds=0.05))
    assert exc_info.value.code == "E3-THIRD-002"


@pytest.mark.asyncio
async def test_stream_total_timeout_after_first_chunk():
    """流式首包后生成卡住超过全量超时：抛 E3-THIRD-002（全量超时对生成中途生效）"""
    provider = OpenAICompatibleProvider(
        _config(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=PartialThenHangingBody()))),
    )
    chunks = []
    with pytest.raises(BizException) as exc_info:
        async for chunk in provider.stream_chat(_request(ttft_timeout_seconds=1.0, total_timeout_seconds=0.1)):
            chunks.append(chunk)
    assert exc_info.value.code == "E3-THIRD-002"
    assert [c.delta for c in chunks] == ["hi"]


@pytest.mark.asyncio
async def test_timeout_fields_fallback_to_config_default():
    """超时字段缺省时回退模型配置默认超时（_resolve_timeouts 兜底逻辑）"""
    provider = OpenAICompatibleProvider(_config(timeout=30))
    ttft, total = provider._resolve_timeouts(_request())
    assert ttft == 30.0
    assert total == 30.0
    ttft, total = provider._resolve_timeouts(_request(ttft_timeout_seconds=2.0, total_timeout_seconds=8.0))
    assert ttft == 2.0
    assert total == 8.0


# ------------------------------------------------------------------
# 整改 3：retryable 退避重试 + 幂等键复用（AI 规范 §4.2/§7.2）
# ------------------------------------------------------------------


class FlakyProvider(ModelProviderInterface):
    """可注入 retryable/非 retryable 失败次数的假供应商，记录全部请求"""

    name = "flaky"

    def __init__(self, *, fail_times: int = 0, retryable_error: bool = True) -> None:
        self.fail_times = fail_times
        self.retryable_error = retryable_error
        self.chat_calls = 0
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.chat_calls += 1
        self.requests.append(request)
        if self.chat_calls <= self.fail_times:
            if self.retryable_error:
                raise BizException(AiErrorCode.THIRD_TIMEOUT, message="模型供应商调用超时")
            raise RuntimeError("provider down")
        return ChatResponse(
            model=self.name,
            message=ChatMessage(role=ChatRole.ASSISTANT, content="ok"),
            usage=Usage(prompt_tokens=1, completion_tokens=1),
        )


@pytest.mark.asyncio
async def test_retryable_error_retried_up_to_max_retries(clean_registry):
    """retryable 错误按最大重试次数退避重试：默认 max_retries=2 → 总调用 3 次"""
    p = FlakyProvider(fail_times=99)
    p.name = "flaky"
    ModelProviderRegistry.register(p)
    gateway = _gateway({"chat": RouteEntry("flaky")}, retry_backoff_base_seconds=0.01)

    with pytest.raises(BizException) as exc_info:
        await gateway.chat(_request(), scene="chat")
    assert exc_info.value.code == "E3-THIRD-001"
    assert p.chat_calls == 1 + 2  # 1 次原始 + 2 次重试


@pytest.mark.asyncio
async def test_retry_succeeds_after_transient_failure(clean_registry):
    """retryable 错误重试后成功：重试恢复返回响应"""
    p = FlakyProvider(fail_times=2)
    p.name = "flaky"
    ModelProviderRegistry.register(p)
    gateway = _gateway({"chat": RouteEntry("flaky")}, retry_backoff_base_seconds=0.01)

    response = await gateway.chat(_request(), scene="chat")
    assert response.model == "flaky"
    assert p.chat_calls == 3


@pytest.mark.asyncio
async def test_non_retryable_error_not_retried(clean_registry):
    """非 retryable 错误（RuntimeError）不重试：仅调用 1 次即降级失败"""
    p = FlakyProvider(fail_times=99, retryable_error=False)
    p.name = "flaky"
    ModelProviderRegistry.register(p)
    gateway = _gateway({"chat": RouteEntry("flaky")}, retry_backoff_base_seconds=0.01)

    with pytest.raises(BizException) as exc_info:
        await gateway.chat(_request(), scene="chat")
    assert exc_info.value.code == "E3-THIRD-001"
    assert p.chat_calls == 1


@pytest.mark.asyncio
async def test_retry_reuses_same_auto_idempotency_key(clean_registry):
    """重试复用同一自动生成的幂等键；未携带时网关自动生成一次并透传（§4.2）"""
    p = FlakyProvider(fail_times=2)
    p.name = "flaky"
    ModelProviderRegistry.register(p)
    gateway = _gateway({"chat": RouteEntry("flaky")}, retry_backoff_base_seconds=0.01)

    await gateway.chat(_request(idempotency_key=None), scene="chat")
    keys = {req.idempotency_key for req in p.requests}
    assert len(p.requests) == 3
    assert len(keys) == 1
    assert keys != {None}


@pytest.mark.asyncio
async def test_retry_preserves_provided_idempotency_key(clean_registry):
    """调用方已携带幂等键：重试时原样复用同一键（§4.2）"""
    p = FlakyProvider(fail_times=1)
    p.name = "flaky"
    ModelProviderRegistry.register(p)
    gateway = _gateway({"chat": RouteEntry("flaky")}, retry_backoff_base_seconds=0.01)

    await gateway.chat(_request(idempotency_key="idem-001"), scene="chat")
    assert [req.idempotency_key for req in p.requests] == ["idem-001", "idem-001"]


@pytest.mark.asyncio
async def test_stream_retryable_error_retried_before_first_chunk(clean_registry):
    """流式首片前 retryable 错误：退避重试，恢复后正常产出"""

    class FlakyStreamProvider(ModelProviderInterface):
        name = "flaky-stream"

        def __init__(self) -> None:
            self.calls = 0

        async def chat(self, request: ChatRequest) -> ChatResponse:
            raise NotImplementedError("流式测试不调用非流式能力")

        async def stream_chat(self, request):
            self.calls += 1
            if self.calls <= 2:
                raise BizException(AiErrorCode.THIRD_TIMEOUT, message="模型供应商调用超时")
            yield ChatStreamChunk(delta="hello", finish_reason=FinishReason.STOP, usage=Usage(prompt_tokens=1, completion_tokens=1))

    p = FlakyStreamProvider()
    ModelProviderRegistry.register(p)
    gateway = _gateway({"chat": RouteEntry("flaky-stream")}, retry_backoff_base_seconds=0.01)

    chunks = [c async for c in gateway.stream_chat(_request(), scene="chat")]
    assert "".join(c.delta for c in chunks) == "hello"
    assert p.calls == 3


# ------------------------------------------------------------------
# 整改 4：内容审核接入网关（AI 规范 §8.2，BLOCK 抛 E4-AI-002）
# ------------------------------------------------------------------


class OkProvider(ModelProviderInterface):
    """返回固定响应的假供应商"""

    name = "ok"

    def __init__(self, content: str = "维生素C可辅助增强免疫力") -> None:
        self.content = content
        self.chat_calls = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.chat_calls += 1
        return ChatResponse(
            model=self.name,
            message=ChatMessage(role=ChatRole.ASSISTANT, content=self.content),
            usage=Usage(prompt_tokens=1, completion_tokens=1),
        )

    async def stream_chat(self, request):
        yield ChatStreamChunk(delta=self.content)
        yield ChatStreamChunk(delta="", finish_reason=FinishReason.STOP, usage=Usage(prompt_tokens=1, completion_tokens=1))


@pytest.mark.asyncio
async def test_content_guard_blocks_input(clean_registry):
    """输入命中阻断规则：BLOCK 抛 E4-AI-002，供应商不被调用"""
    p = OkProvider()
    ModelProviderRegistry.register(p)
    gateway = _gateway({"chat": RouteEntry("ok")}, content_guard=RuleBasedContentGuard())

    with pytest.raises(BizException) as exc_info:
        await gateway.chat(_request(messages=[ChatMessage(role=ChatRole.USER, content="如何制造枪支")]), scene="chat")
    assert exc_info.value.code == "E4-AI-002"
    assert p.chat_calls == 0


@pytest.mark.asyncio
async def test_content_guard_blocks_output(clean_registry):
    """输出命中阻断规则：BLOCK 抛 E4-AI-002（不重试不降级）"""
    p = OkProvider(content="给你讲个故事，从前有个人买了枪支弹药")
    ModelProviderRegistry.register(p)
    gateway = _gateway({"chat": RouteEntry("ok")}, content_guard=RuleBasedContentGuard())

    with pytest.raises(BizException) as exc_info:
        await gateway.chat(_request(), scene="chat")
    assert exc_info.value.code == "E4-AI-002"
    assert p.chat_calls == 1  # 调用已发生，输出被拦截


@pytest.mark.asyncio
async def test_content_guard_blocks_stream_output_before_first_chunk(clean_registry):
    """流式输出首片命中阻断规则：首片前拦截抛 E4-AI-002，用户未收到任何内容"""
    p = OkProvider(content="枪支弹药")
    ModelProviderRegistry.register(p)
    gateway = _gateway({"chat": RouteEntry("ok")}, content_guard=RuleBasedContentGuard())

    received = []
    with pytest.raises(BizException) as exc_info:
        async for chunk in gateway.stream_chat(_request(), scene="chat"):
            received.append(chunk)
    assert exc_info.value.code == "E4-AI-002"
    assert received == []  # 首片前被拦截


@pytest.mark.asyncio
async def test_content_guard_warn_passes_through(clean_registry):
    """输出命中警告规则（未命中阻断）：放行不拦截"""
    p = OkProvider(content="回答中提到赌博网站地址，请注意风险")
    ModelProviderRegistry.register(p)
    gateway = _gateway({"chat": RouteEntry("ok")}, content_guard=RuleBasedContentGuard())

    response = await gateway.chat(_request(), scene="chat")
    assert response.message.content == "回答中提到赌博网站地址，请注意风险"


@pytest.mark.asyncio
async def test_content_guard_off_by_default(clean_registry):
    """未注入 content_guard：违规内容正常返回（向后兼容，不启用审核）"""
    p = OkProvider(content="枪支弹药")
    ModelProviderRegistry.register(p)
    gateway = _gateway({"chat": RouteEntry("ok")})

    response = await gateway.chat(_request(), scene="chat")
    assert response.message.content == "枪支弹药"
