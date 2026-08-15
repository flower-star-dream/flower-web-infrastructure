"""
模型网关 AI 缓存接入单元测试

@Author: 花海
@Date: 2026/08/15 11:00
@Description: 验证 AI-4 整改：AICache 注入网关后 chat 缓存命中/未命中路径与
              命中/未命中指标、默认不启用（向后兼容）、模型版本/用户维度失效、
              流式不缓存、降级响应不落缓存。
"""
import pytest

from web_infra.ai import (
    AICache,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatRole,
    ChatStreamChunk,
    FinishReason,
    ModelGateway,
    ModelProviderInterface,
    ModelProviderRegistry,
    Usage,
)
from web_infra.ai.model_gateway import ModelRouter, RouteEntry
from web_infra.monitoring.ai_metrics import AI_LLM_CALLS_TOTAL


class _FakeProvider(ModelProviderInterface):
    """可控假供应商：chat/stream 调用计数"""

    name = "fake"

    def __init__(self, content: str = "ok") -> None:
        self.content = content
        self.chat_calls = 0
        self.stream_calls = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.chat_calls += 1
        return ChatResponse(
            model=self.name,
            message=ChatMessage(role=ChatRole.ASSISTANT, content=self.content),
            usage=Usage(prompt_tokens=3, completion_tokens=3),
        )

    async def stream_chat(self, request):
        self.stream_calls += 1
        yield ChatStreamChunk(delta=self.content)
        yield ChatStreamChunk(delta="", finish_reason=FinishReason.STOP, usage=Usage(prompt_tokens=3, completion_tokens=3))


class _FlakyProvider(ModelProviderInterface):
    """可注入失败的主模型：验证降级响应不落缓存"""

    name = "flaky"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        if self.fail:
            raise RuntimeError("primary down")
        return ChatResponse(
            model=self.name,
            message=ChatMessage(role=ChatRole.ASSISTANT, content="primary ok"),
            usage=Usage(prompt_tokens=1, completion_tokens=1),
        )

    async def stream_chat(self, request):
        raise NotImplementedError("本测试不涉及流式")


@pytest.fixture
def clean_registry():
    """测试后清理全局供应商注册表，避免污染其他用例"""
    before = dict(ModelProviderRegistry._providers)
    yield
    ModelProviderRegistry._providers.clear()
    ModelProviderRegistry._providers.update(before)


def _gateway(routes: dict[str, RouteEntry], *, ai_cache=None, **kwargs) -> ModelGateway:
    """构造网关：路由 + 可选 AICache/重试参数"""
    return ModelGateway(ModelRouter(routes), ai_cache=ai_cache, **kwargs)


def _request(model: str = "fake", **overrides) -> ChatRequest:
    """构造最小对话请求（默认带 model_version 参与缓存 Key）"""
    base = dict(model=model, messages=[ChatMessage(role=ChatRole.USER, content="hello")], model_version="1.0")
    base.update(overrides)
    return ChatRequest(**base)


def _counter(model: str, outcome: str) -> float:
    """读取 ai_llm_calls_total 指定 outcome 累计值。

    遍历全部 service 标签求和（避免依赖全局 init_ai_metrics 的调用顺序），
    且仅统计主系列——prometheus 新版 Counter 的 collect() 会额外生成
    ai_llm_calls_created 辅助系列（值为创建时间戳），须按 sample.name 跳过。
    """
    total = 0.0
    for metric in AI_LLM_CALLS_TOTAL.collect():
        for sample in metric.samples:
            if sample.name != "ai_llm_calls_total":
                continue  # 跳过 _created 辅助系列（值为时间戳）
            if sample.labels.get("model") == model and sample.labels.get("outcome") == outcome:
                total += sample.value
    return total


# ------------------------------------------------------------------
# AI-4：chat 缓存命中/未命中路径
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_cache_miss_then_hit(clean_registry):
    """未命中调用模型并写缓存（cache_miss）；同参再次调用命中直接返回（cache_hit）"""
    provider = _FakeProvider(content="缓存内容")
    ModelProviderRegistry.register(provider)
    gateway = _gateway({"chat": RouteEntry("fake")}, ai_cache=AICache())

    first = await gateway.chat(_request(), scene="chat", tenant_id="t1", user_id="u1")
    assert first.message.content == "缓存内容"
    assert provider.chat_calls == 1
    assert _counter("fake", "cache_miss") == 1
    assert _counter("fake", "success") == 1

    second = await gateway.chat(_request(), scene="chat", tenant_id="t1", user_id="u1")
    assert second.message.content == "缓存内容"
    assert provider.chat_calls == 1  # 命中后不再调用模型
    assert _counter("fake", "cache_hit") == 1


@pytest.mark.asyncio
async def test_chat_cache_disabled_by_default(clean_registry):
    """未注入 AICache：每次调用均走模型，无缓存路径（向后兼容）"""
    provider = _FakeProvider()
    ModelProviderRegistry.register(provider)
    gateway = _gateway({"chat": RouteEntry("fake")})

    await gateway.chat(_request(), scene="chat")
    await gateway.chat(_request(), scene="chat")
    assert provider.chat_calls == 2


@pytest.mark.asyncio
async def test_chat_cache_user_isolation(clean_registry):
    """同一 Prompt 不同用户：各自未命中（用户维度隔离，防跨用户串扰）"""
    provider = _FakeProvider()
    ModelProviderRegistry.register(provider)
    gateway = _gateway({"chat": RouteEntry("fake")}, ai_cache=AICache())

    await gateway.chat(_request(), scene="chat", tenant_id="t1", user_id="u1")
    await gateway.chat(_request(), scene="chat", tenant_id="t1", user_id="u2")
    assert provider.chat_calls == 2


@pytest.mark.asyncio
async def test_chat_cache_model_version_invalidates(clean_registry):
    """模型版本变更：缓存 Key 变化，同 Prompt 重新调用模型（版本维度自然失效）"""
    provider = _FakeProvider()
    ModelProviderRegistry.register(provider)
    gateway = _gateway({"chat": RouteEntry("fake")}, ai_cache=AICache())

    await gateway.chat(_request(model_version="1.0"), scene="chat", tenant_id="t1", user_id="u1")
    await gateway.chat(_request(model_version="2.0"), scene="chat", tenant_id="t1", user_id="u1")
    assert provider.chat_calls == 2


@pytest.mark.asyncio
async def test_chat_cache_tenant_isolation(clean_registry):
    """不同租户互不命中（缓存租户隔离）"""
    provider = _FakeProvider()
    ModelProviderRegistry.register(provider)
    gateway = _gateway({"chat": RouteEntry("fake")}, ai_cache=AICache())

    await gateway.chat(_request(), scene="chat", tenant_id="t1", user_id="u1")
    await gateway.chat(_request(), scene="chat", tenant_id="t2", user_id="u1")
    assert provider.chat_calls == 2


# ------------------------------------------------------------------
# AI-4：流式不缓存 / 降级响应不落缓存
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_chat_not_cached(clean_registry):
    """流式输出不缓存：流式调用后缓存无写入，随后同参 chat 仍走模型（避免过度设计）"""
    provider = _FakeProvider()
    ModelProviderRegistry.register(provider)
    gateway = _gateway({"chat": RouteEntry("fake")}, ai_cache=AICache())

    chunks = [c async for c in gateway.stream_chat(_request(), scene="chat")]
    assert "".join(c.delta for c in chunks) == "ok"
    assert provider.stream_calls == 1
    # 流式未写缓存：同参非流式调用仍触发模型
    await gateway.chat(_request(), scene="chat", tenant_id="t1", user_id="u1")
    assert provider.chat_calls == 1


@pytest.mark.asyncio
async def test_degraded_response_not_cached(clean_registry):
    """主模型失败降级备用：降级响应不写缓存，下次调用仍走模型（防主模型恢复后命中降级内容）"""
    primary = _FlakyProvider(fail=True)
    backup = _FakeProvider(content="备用回答")
    backup.name = "backup"
    ModelProviderRegistry.register(primary)
    ModelProviderRegistry.register(backup)
    gateway = _gateway({"chat": RouteEntry("flaky", backups=("backup",))}, ai_cache=AICache())

    first = await gateway.chat(_request("backup"), scene="chat", tenant_id="t1", user_id="u1")
    assert first.message.content == "备用回答"
    assert backup.chat_calls == 1

    second = await gateway.chat(_request("backup"), scene="chat", tenant_id="t1", user_id="u1")
    assert second.message.content == "备用回答"
    assert backup.chat_calls == 2  # 未命中缓存，再次降级调用
