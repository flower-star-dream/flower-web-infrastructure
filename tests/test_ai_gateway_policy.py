"""
AI 网关增强（AI-2/3/5/6/8）单元测试

@Author: 花海
@Date: 2026/08/15
@Description: 覆盖第 7 批组 3 整改：
              AI-2 配额覆盖 chat/stream/embed 三入口 + user/scene 维度参与；
              AI-3 用量记录聚合字段透传（model_code/tenant_id/scene/provider）；
              AI-5 流开始后异常通过统一流内错误分片终止（error + finish_reason=ERROR）；
              AI-6 相似度阈值默认 0.75（低相关降级为纯生成）；
              AI-8 模型访问权限校验 SPI（AllowAll 默认放行 / 自定义策略拒绝抛 E2-PERM-*）。
"""
import asyncio

import pytest

from web_infra.ai import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatRole,
    ChatStreamChunk,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingProviderInterface,
    FinishReason,
    InMemoryVectorStore,
    ModelGateway,
    ModelProviderInterface,
    ModelProviderRegistry,
    QuotaConfig,
    QuotaManager,
    RerankerInterface,
    Retriever,
    Usage,
    UsageAccounting,
    UsageRecord,
    UsageRecordStoreInterface,
)
from web_infra.ai.model_access_policy import ModelAccessPolicy
from web_infra.ai.model_gateway import ModelRouter, RouteEntry
from web_infra.context import RequestContext
from web_infra.db.tenant_guard import NO_TENANT
from web_infra.error import BizException, PermException
from web_infra.error.ai_error_code import AiErrorCode


# ---------------------------------------------------------------------------
# 假供应商 / 工具类
# ---------------------------------------------------------------------------

class FakeProvider(ModelProviderInterface):
    """可控假供应商：chat/stream/embed 三能力齐备，可按需注入流中途失败"""

    name = "p1"

    def __init__(self, *, fail_stream_after_start: bool = False) -> None:
        self.fail_stream_after_start = fail_stream_after_start
        self.chat_calls = 0
        self.embed_calls = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """非流式对话（固定响应 + Token 用量 10/5）"""
        self.chat_calls += 1
        return ChatResponse(
            model=self.name,
            message=ChatMessage(role=ChatRole.ASSISTANT, content="ok"),
            usage=Usage(prompt_tokens=10, completion_tokens=5),
        )

    async def stream_chat(self, request: ChatRequest):
        """流式对话（可注入首个分片后失败）"""
        yield ChatStreamChunk(delta="hello")
        if self.fail_stream_after_start:
            raise RuntimeError("mid-stream failure")
        yield ChatStreamChunk(
            delta=" world",
            finish_reason=FinishReason.STOP,
            usage=Usage(prompt_tokens=10, completion_tokens=5),
        )

    async def embedding(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """向量化（固定向量 + Token 用量 3/0）"""
        self.embed_calls += 1
        return EmbeddingResponse(model=self.name, embeddings=[[0.1, 0.2]], usage=Usage(prompt_tokens=3, completion_tokens=0))


class _SpyQuotaManager(QuotaManager):
    """记录配额检查调用（scope, scope_value）的假配额管理器"""

    def __init__(self) -> None:
        super().__init__()
        self.checked: list[tuple[str, str]] = []

    async def check_and_consume(self, scope, scope_value, *, tokens=0, cost=0.0, config=None) -> None:
        """记录后透传父类检查（默认配置无限制，仅记录）"""
        self.checked.append((scope, scope_value))
        return await super().check_and_consume(scope, scope_value, tokens=tokens, cost=cost, config=config)


class _DenyPolicy(ModelAccessPolicy):
    """拒绝所有模型访问的权限策略（AI-8 测试）"""

    def check_access(self, model_name: str, tenant_id: str, user_id: str, scene: str | None = None) -> bool:
        """恒返回 False：一律拒绝"""
        return False


class _FakeEmbedding(EmbeddingProviderInterface):
    """假嵌入：按字符构造向量（供向量存储写入/检索）"""

    def embed(self, text: str) -> list[float]:
        return [float(ord(ch)) for ch in text] or [0.0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class _LowScoreReranker(RerankerInterface):
    """返回固定低分的重排器（模拟低相关文档）"""

    def __init__(self, score: float = 0.1) -> None:
        self.score = score

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [self.score] * len(documents)


@pytest.fixture
def clean_registry():
    """测试后清理全局供应商注册表，避免污染其他用例"""
    before = dict(ModelProviderRegistry._providers)
    yield
    ModelProviderRegistry._providers.clear()
    ModelProviderRegistry._providers.update(before)


def _gateway(routes: dict[str, RouteEntry], **kwargs) -> ModelGateway:
    """构造网关：路由 + 可选配额/计费/权限策略"""
    return ModelGateway(ModelRouter(routes), **kwargs)


def _request(model: str = "p1") -> ChatRequest:
    """构造最小对话请求"""
    return ChatRequest(model=model, messages=[])


def _store_with(texts: dict[str, str]) -> InMemoryVectorStore:
    """构造含给定文本向量的内存向量存储（no-tenant 命名空间）"""
    RequestContext.clear()
    store = InMemoryVectorStore()
    emb = _FakeEmbedding()
    store.add(NO_TENANT, list(texts.keys()), emb.embed_batch(list(texts.values())))
    return store


# ---------------------------------------------------------------------------
# AI-2：配额覆盖 chat/stream/embed + user/scene 维度
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quota_checked_on_chat_stream_embed(clean_registry):
    """AI-2：chat/stream_chat/embed 三入口统一配额检查，tenant/user/scene 维度参与"""
    p1 = FakeProvider()
    p1.name = "p1"
    ModelProviderRegistry.register(p1)
    spy = _SpyQuotaManager()
    gateway = _gateway({"chat": RouteEntry("p1")}, quota_manager=spy)

    await gateway.chat(_request("p1"), scene="chat", tenant_id="t1", user_id="u1")
    chunks = [c async for c in gateway.stream_chat(_request("p1"), scene="chat", tenant_id="t1", user_id="u1")]
    assert "".join(c.delta for c in chunks) == "hello world"
    await gateway.embed(EmbeddingRequest(model="p1", input="hello"), scene="chat", tenant_id="t1", user_id="u1")

    # 每个入口均检查 tenant/user/scene 三个维度（共 3 次 × 3 维度）
    assert spy.checked == [
        ("tenant", "t1"), ("user", "u1"), ("scene", "chat"),
        ("tenant", "t1"), ("user", "u1"), ("scene", "chat"),
        ("tenant", "t1"), ("user", "u1"), ("scene", "chat"),
    ]


@pytest.mark.asyncio
async def test_quota_user_dimension_enforced(clean_registry):
    """AI-2：user 维度独立参与限流（不同租户同用户第二次调用超限 E1-RATE-000）"""
    p1 = FakeProvider()
    p1.name = "p1"
    ModelProviderRegistry.register(p1)
    gateway = _gateway(
        {"chat": RouteEntry("p1")},
        quota_manager=QuotaManager(default_config=QuotaConfig(max_calls=1, window_seconds=3600)),
    )

    await gateway.chat(_request("p1"), scene="chat", tenant_id="t1", user_id="u1")
    with pytest.raises(BizException) as exc_info:
        await gateway.chat(_request("p1"), scene="chat", tenant_id="t2", user_id="u1")
    assert exc_info.value.code == "E1-RATE-000"  # tenant t2 未超，user u1 已超


@pytest.mark.asyncio
async def test_token_quota_accumulated_and_blocked_next_call(clean_registry):
    """AI-2：Token 配额按实际用量累计，超限由下一次入口检查拦截（E1-RATE-000）"""
    p1 = FakeProvider()
    p1.name = "p1"
    ModelProviderRegistry.register(p1)
    # 每次调用累计 15 tokens（10 prompt + 5 completion）
    gateway = _gateway(
        {"chat": RouteEntry("p1")},
        quota_manager=QuotaManager(default_config=QuotaConfig(max_tokens=20, window_seconds=3600)),
    )

    await gateway.chat(_request("p1"), scene="chat", tenant_id="t1")  # 第 1 次：入口通过，累计 15
    await gateway.chat(_request("p1"), scene="chat", tenant_id="t1")  # 第 2 次：入口 15≤20 通过，累计 30（超限仅告警，本次正常返回）
    with pytest.raises(BizException) as exc_info:
        await gateway.chat(_request("p1"), scene="chat", tenant_id="t1")  # 第 3 次：入口累计 30>20 拦截
    assert exc_info.value.code == "E1-RATE-000"


# ---------------------------------------------------------------------------
# AI-3：用量记录聚合字段透传
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usage_record_aggregation_fields(clean_registry):
    """AI-3：用量记录透传 model_code/tenant_id/scene/provider 聚合维度"""
    saved: list[UsageRecord] = []

    class _Store(UsageRecordStoreInterface):
        async def save(self, record: UsageRecord) -> None:
            saved.append(record)

    p1 = FakeProvider()
    p1.name = "p1"
    ModelProviderRegistry.register(p1)
    accounting = UsageAccounting(record_store=_Store())
    gateway = _gateway({"chat": RouteEntry("p1"), "rag": RouteEntry("p1")}, usage_accounting=accounting)

    await gateway.chat(_request("p1"), scene="rag", tenant_id="t1", user_id="u1")
    for _ in range(50):
        if saved:
            break
        await asyncio.sleep(0.01)
    assert len(saved) == 1
    record = saved[0]
    assert record.model_code == "p1"
    assert record.provider == "p1"  # provider.name
    assert record.tenant_id == "t1"
    assert record.scene == "rag"
    assert record.prompt_tokens == 10
    assert record.completion_tokens == 5

    # 按租户/场景聚合维度可独立分组
    tenant_agg = {item["tenant_id"]: item for item in accounting.aggregate(group_by=("tenant_id",))}
    assert tenant_agg["t1"]["total_tokens"] == 15
    scene_agg = {item["scene"]: item for item in accounting.aggregate(group_by=("scene",))}
    assert scene_agg["rag"]["calls"] == 1


# ---------------------------------------------------------------------------
# AI-5：流开始后异常 → 统一流内错误分片终止
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_error_chunk_after_start(clean_registry):
    """AI-5：流产出部分分片后供应商抛错 → 产出 error 分片终止（E4-AI-004 + finish_reason=ERROR）"""
    p1 = FakeProvider(fail_stream_after_start=True)
    p1.name = "p1"
    ModelProviderRegistry.register(p1)
    gateway = _gateway({"chat": RouteEntry("p1")})

    chunks = [c async for c in gateway.stream_chat(_request("p1"), scene="chat")]
    assert "".join(c.delta for c in chunks) == "hello"  # 已产出分片保留
    assert chunks[-1].finish_reason == FinishReason.ERROR  # 错误终止分片
    assert chunks[-1].error == AiErrorCode.AI_GENERATION_FAILED.code  # RuntimeError → E4-AI-004
    assert chunks[-1].usage is None


@pytest.mark.asyncio
async def test_stream_error_chunk_carries_web_infra_error_code(clean_registry):
    """AI-5：流内异常为 WebInfraException 时 error 分片携带其错误码（E3-THIRD-001）"""

    class _WebInfraFailStreamProvider(FakeProvider):
        async def stream_chat(self, request: ChatRequest):
            yield ChatStreamChunk(delta="partial")
            raise BizException(AiErrorCode.THIRD_UNAVAILABLE, message="provider down")

    p1 = _WebInfraFailStreamProvider()
    p1.name = "p1"
    ModelProviderRegistry.register(p1)
    gateway = _gateway({"chat": RouteEntry("p1")})

    chunks = [c async for c in gateway.stream_chat(_request("p1"), scene="chat")]
    assert "".join(c.delta for c in chunks) == "partial"
    assert chunks[-1].error == AiErrorCode.THIRD_UNAVAILABLE.code
    assert chunks[-1].finish_reason == FinishReason.ERROR


# ---------------------------------------------------------------------------
# AI-6：相似度阈值默认 0.75（低相关降级为纯生成）
# ---------------------------------------------------------------------------


def test_retriever_default_threshold_filters_low_similarity():
    """AI-6：默认阈值 0.75 过滤低相似度（0.1 < 0.75 结果被过滤，降级返回空列表）"""
    store = _store_with({"d1": "目标文档一"})
    retriever = Retriever(store, _FakeEmbedding(), reranker=_LowScoreReranker(0.1), document_texts={"d1": "目标文档一"})
    assert retriever.search("目标") == []  # 低相关降级为纯生成


def test_retriever_default_threshold_keeps_high_similarity():
    """AI-6：默认阈值 0.75 保留高相似度（Identity 得分 1.0 ≥ 0.75）"""
    store = _store_with({"d1": "目标文档一"})
    retriever = Retriever(store, _FakeEmbedding(), document_texts={"d1": "目标文档一"})
    results = retriever.search("目标")
    assert len(results) == 1


def test_retriever_explicit_min_score_respected():
    """AI-6：调用方显式传 min_score 时尊重其值（0.1 ≥ 0.05 保留）"""
    store = _store_with({"d1": "目标文档一"})
    retriever = Retriever(
        store, _FakeEmbedding(), reranker=_LowScoreReranker(0.1), min_score=0.05, document_texts={"d1": "目标文档一"}
    )
    results = retriever.search("目标")
    assert len(results) == 1


# ---------------------------------------------------------------------------
# AI-8：模型访问权限校验 SPI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_access_policy_default_allow_all(clean_registry):
    """AI-8：默认 AllowAll 放行（未注入策略时 chat/stream/embed 调用成功）"""
    p1 = FakeProvider()
    p1.name = "p1"
    ModelProviderRegistry.register(p1)
    gateway = _gateway({"chat": RouteEntry("p1")})

    response = await gateway.chat(_request("p1"), scene="chat", tenant_id="t1", user_id="u1")
    assert response.message.content == "ok"
    chunks = [c async for c in gateway.stream_chat(_request("p1"), scene="chat", tenant_id="t1", user_id="u1")]
    assert chunks[-1].finish_reason == FinishReason.STOP
    embedding = await gateway.embed(EmbeddingRequest(model="p1", input="hi"), scene="chat", tenant_id="t1", user_id="u1")
    assert embedding.embeddings == [[0.1, 0.2]]


@pytest.mark.asyncio
async def test_access_policy_deny_raises_perm(clean_registry):
    """AI-8：自定义策略拒绝时 chat/stream_chat/embed 抛 E2-PERM-*（供应商不被调用）"""
    p1 = FakeProvider()
    p1.name = "p1"
    ModelProviderRegistry.register(p1)
    gateway = _gateway({"chat": RouteEntry("p1")}, access_policy=_DenyPolicy())

    with pytest.raises(PermException) as exc_info:
        await gateway.chat(_request("p1"), scene="chat", tenant_id="t1", user_id="u1")
    assert exc_info.value.code == "E2-PERM-000"
    assert p1.chat_calls == 0  # 权限拦截先于模型调用

    with pytest.raises(PermException):
        async for _ in gateway.stream_chat(_request("p1"), scene="chat", tenant_id="t1", user_id="u1"):
            pass

    with pytest.raises(PermException):
        await gateway.embed(EmbeddingRequest(model="p1", input="hi"), scene="chat", tenant_id="t1", user_id="u1")
