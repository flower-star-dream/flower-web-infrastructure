"""
统一模型网关单元测试

@Author: 花海
@Date: 2026/08/14 17:00
@Description: 验证场景路由、主备降级、流式降级限制、配额、计费打点与
              未配置快速失败（AI 规范 §2.2/§2.3/§4.2/§5.3）。
"""
import pytest

from web_infra.ai import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatRole,
    ChatStreamChunk,
    EmbeddingRequest,
    FinishReason,
    ModelGateway,
    ModelProviderInterface,
    ModelProviderRegistry,
    QuotaConfig,
    QuotaManager,
    Usage,
    UsageAccounting,
)
from web_infra.ai.model_gateway import ModelRouter, RouteEntry
from web_infra.error import BizException
from web_infra.error.ai_error_code import AiErrorCode


class FakeProvider(ModelProviderInterface):
    """可控的假供应商：可按需注入 chat/流式中途失败"""

    name = "fake"

    def __init__(self, *, fail_chat: bool = False, fail_stream_before_start: bool = False, fail_stream_after_start: bool = False) -> None:
        self.fail_chat = fail_chat
        self.fail_stream_before_start = fail_stream_before_start
        self.fail_stream_after_start = fail_stream_after_start
        self.chat_calls = 0
        self.last_request: ChatRequest | None = None

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """非流式对话（可注入失败）"""
        self.chat_calls += 1
        self.last_request = request
        if self.fail_chat:
            raise RuntimeError(f"{self.name} down")
        return ChatResponse(
            model=self.name,
            message=ChatMessage(role=ChatRole.ASSISTANT, content="ok"),
            usage=Usage(prompt_tokens=10, completion_tokens=5),
        )

    async def stream_chat(self, request: ChatRequest):
        """流式对话（可注入首分片前后失败）"""
        if self.fail_stream_before_start:
            raise RuntimeError(f"{self.name} stream down")
        yield ChatStreamChunk(delta="hello")
        if self.fail_stream_after_start:
            raise RuntimeError(f"{self.name} mid-stream failure")
        yield ChatStreamChunk(
            delta=" world",
            finish_reason=FinishReason.STOP,
            usage=Usage(prompt_tokens=10, completion_tokens=5),
        )

    async def embedding(self, request: EmbeddingRequest):
        """向量化"""
        return await super().embedding(request)  # type: ignore[reportUnreachable]


@pytest.fixture
def clean_registry():
    """测试后清理全局供应商注册表，避免污染其他用例"""
    before = dict(ModelProviderRegistry._providers)
    yield
    ModelProviderRegistry._providers.clear()
    ModelProviderRegistry._providers.update(before)


def _gateway(
    routes: dict[str, RouteEntry],
    default_scene: str = "",
    *,
    quota_manager: QuotaManager | None = None,
    usage_accounting: UsageAccounting | None = None,
) -> ModelGateway:
    """构造网关：路由 + 可选配额/计费"""
    return ModelGateway(
        ModelRouter(routes, default_scene=default_scene),
        quota_manager=quota_manager,
        usage_accounting=usage_accounting,
    )


def _request(model: str = "fake", *, idempotency_key: str | None = None) -> ChatRequest:
    """构造最小对话请求"""
    return ChatRequest(model=model, messages=[], idempotency_key=idempotency_key)


# ------------------------------------------------------------------
# 路由与快速失败
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_routes_by_scene(clean_registry):
    """按场景路由到主模型"""
    p1 = FakeProvider()
    p1.name = "p1"
    ModelProviderRegistry.register(p1)
    gateway = _gateway({"chat": RouteEntry("p1")})

    response = await gateway.chat(_request("p1"), scene="chat")
    assert response.model == "p1"
    assert p1.chat_calls == 1


@pytest.mark.asyncio
async def test_chat_falls_back_to_default_scene(clean_registry):
    """未配置场景回退默认场景（AI 规范 §2.3）"""
    p1 = FakeProvider()
    p1.name = "p1"
    ModelProviderRegistry.register(p1)
    gateway = _gateway({"chat": RouteEntry("p1")}, default_scene="chat")

    response = await gateway.chat(_request("p1"), scene="qa")
    assert response.model == "p1"


@pytest.mark.asyncio
async def test_chat_unconfigured_scene_fails_fast(clean_registry):
    """场景未配置且无默认场景：快速失败 E4-AI-001（AI 规范 §2.1）"""
    gateway = _gateway({})
    with pytest.raises(BizException) as exc_info:
        await gateway.chat(_request(), scene="qa")
    assert exc_info.value.code == "E4-AI-001"


@pytest.mark.asyncio
async def test_chat_unregistered_provider_fails_fast(clean_registry):
    """路由命中但供应商未注册：快速失败 E4-AI-001"""
    gateway = _gateway({"chat": RouteEntry("ghost")})
    with pytest.raises(BizException) as exc_info:
        await gateway.chat(_request("ghost"), scene="chat")
    assert exc_info.value.code == "E4-AI-001"


# ------------------------------------------------------------------
# 主备降级
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_fallback_to_backup(clean_registry):
    """主模型失败自动降级备用模型（AI 规范 §2.3）"""
    p1 = FakeProvider(fail_chat=True)
    p1.name = "p1"
    p2 = FakeProvider()
    p2.name = "p2"
    ModelProviderRegistry.register(p1)
    ModelProviderRegistry.register(p2)
    gateway = _gateway({"chat": RouteEntry("p1", backups=("p2",))})

    response = await gateway.chat(_request("p2"), scene="chat")
    assert response.model == "p2"
    assert p1.chat_calls == 1
    assert p2.chat_calls == 1


@pytest.mark.asyncio
async def test_chat_all_candidates_failed(clean_registry):
    """主备全部失败：抛 E3-THIRD-001（可重试）"""
    p1 = FakeProvider(fail_chat=True)
    p1.name = "p1"
    p2 = FakeProvider(fail_chat=True)
    p2.name = "p2"
    ModelProviderRegistry.register(p1)
    ModelProviderRegistry.register(p2)
    gateway = _gateway({"chat": RouteEntry("p1", backups=("p2",))})

    with pytest.raises(BizException) as exc_info:
        await gateway.chat(_request("p2"), scene="chat")
    assert exc_info.value.code == "E3-THIRD-001"


# ------------------------------------------------------------------
# 流式降级限制（AI 规范 §4.2）
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_fallback_before_first_chunk(clean_registry):
    """未产出首分片前允许降级备用模型"""
    p1 = FakeProvider(fail_stream_before_start=True)
    p1.name = "p1"
    p2 = FakeProvider()
    p2.name = "p2"
    ModelProviderRegistry.register(p1)
    ModelProviderRegistry.register(p2)
    gateway = _gateway({"chat": RouteEntry("p1", backups=("p2",))})

    chunks = [c async for c in gateway.stream_chat(_request("p2"), scene="chat")]
    assert "".join(c.delta for c in chunks) == "hello world"
    assert chunks[-1].finish_reason == FinishReason.STOP


@pytest.mark.asyncio
async def test_stream_no_retry_after_first_chunk(clean_registry):
    """已产出后主模型失败：不降级，产出统一流内错误分片终止（AI-5 整改）"""
    p1 = FakeProvider(fail_stream_after_start=True)
    p1.name = "p1"
    p2 = FakeProvider()
    p2.name = "p2"
    ModelProviderRegistry.register(p1)
    ModelProviderRegistry.register(p2)
    gateway = _gateway({"chat": RouteEntry("p1", backups=("p2",))})

    # AI-5：流开始后异常通过统一流内错误分片终止（error 携带错误码，finish_reason=ERROR），而非抛异常
    chunks = [c async for c in gateway.stream_chat(_request("p2"), scene="chat")]
    assert "".join(c.delta for c in chunks) == "hello"
    assert chunks[-1].finish_reason == FinishReason.ERROR
    assert chunks[-1].error == AiErrorCode.AI_GENERATION_FAILED.code  # 供应商 RuntimeError → 统一 E4-AI-004
    assert p2.chat_calls == 0  # 未触发降级


# ------------------------------------------------------------------
# 配额 / 计费 / 幂等透传
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_quota_enforced(clean_registry):
    """网关配额按租户维度限调用次数：超限抛 E1-RATE-000"""
    p1 = FakeProvider()
    p1.name = "p1"
    ModelProviderRegistry.register(p1)
    gateway = _gateway(
        {"chat": RouteEntry("p1")},
        quota_manager=QuotaManager(default_config=QuotaConfig(max_calls=1, window_seconds=3600)),
    )

    await gateway.chat(_request("p1"), scene="chat", tenant_id="t1")
    with pytest.raises(BizException) as exc_info:
        await gateway.chat(_request("p1"), scene="chat", tenant_id="t1")
    assert exc_info.value.code == "E1-RATE-000"


@pytest.mark.asyncio
async def test_chat_usage_accounting_recorded(clean_registry):
    """成功调用后计费打点：用量聚合累计"""
    p1 = FakeProvider()
    p1.name = "p1"
    ModelProviderRegistry.register(p1)
    accounting = UsageAccounting()
    gateway = _gateway({"chat": RouteEntry("p1")}, usage_accounting=accounting)

    await gateway.chat(_request("p1"), scene="chat")
    aggregate = accounting.aggregate(group_by=("model_code",))
    row = next(item for item in aggregate if item["model_code"] == "p1")
    assert row["prompt_tokens"] == 10
    assert row["completion_tokens"] == 5
    assert row["calls"] == 1


@pytest.mark.asyncio
async def test_chat_idempotency_key_passthrough(clean_registry):
    """幂等键原样透传给供应商（AI 规范 §4.2）"""
    p1 = FakeProvider()
    p1.name = "p1"
    ModelProviderRegistry.register(p1)
    gateway = _gateway({"chat": RouteEntry("p1")})

    await gateway.chat(_request("p1", idempotency_key="idem-001"), scene="chat")
    assert p1.last_request is not None
    assert p1.last_request.idempotency_key == "idem-001"
