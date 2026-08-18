"""
文档切片与向量检索单元测试

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 验证 Markdown 结构块切片（标题/代码块/表格/段落）与检索流程
              （召回 → 邻居扩展 → 重排 → 阈值过滤 → 异常降级），
              以及向量存储/检索的租户维度隔离（多租户规范 §2：禁止跨租户命中知识库内容）。
"""
import pytest

from web_infra.ai.retrieval import (
    MarkdownChunker,
    InMemoryVectorStore,
    Retriever,
    EmbeddingProviderInterface,
    RerankerInterface,
)
from web_infra.context import RequestContext
from web_infra.db.tenant_guard import NO_TENANT


# ---------------------------------------------------------------------------
# 文档切片
# ---------------------------------------------------------------------------

def test_chunk_heading_segments():
    """标题分组：不同标题下文本独立成块，携带标题上下文"""
    doc = "# 引言\n这是引言内容。\n\n# 方法\n这是方法内容。"
    chunks = MarkdownChunker().chunk(doc)
    assert len(chunks) == 2
    assert chunks[0].heading == "引言"
    assert chunks[0].level == 1
    assert "引言内容" in chunks[0].text
    assert chunks[1].heading == "方法"
    assert "方法内容" in chunks[1].text


def test_chunk_code_block_atomic():
    """代码块作为原子块不拆分"""
    doc = "# 示例\n```python\nx = 1\n```\n正文。"
    chunks = MarkdownChunker().chunk(doc)
    texts = [c.text for c in chunks]
    assert "```python\nx = 1\n```" in texts or "x = 1" in texts
    # 代码块内容完整保留
    code_chunk = next(c for c in chunks if "x = 1" in c.text)
    assert "x = 1" in code_chunk.text


def test_chunk_table_atomic():
    """表格作为原子块不拆分"""
    doc = "# 数据\n| 列A | 列B |\n| --- | --- |\n| 1 | 2 |"
    chunks = MarkdownChunker().chunk(doc)
    table_chunk = next(c for c in chunks if "列A" in c.text)
    assert "| 1 | 2 |" in table_chunk.text  # 表格行完整
    assert "列B" in table_chunk.text


def test_chunk_order_monotonic():
    """切片顺序号单调递增"""
    doc = "# A\n文本1\n```py\ncode\n```\n| h |\n|---|\n| v |\n# B\n文本2"
    chunks = MarkdownChunker().chunk(doc)
    orders = [c.order for c in chunks]
    assert orders == sorted(orders)
    assert len(orders) == len(set(orders))


# ---------------------------------------------------------------------------
# 向量存储
# ---------------------------------------------------------------------------

class _FakeEmbedding(EmbeddingProviderInterface):
    """假嵌入：按字符构造向量（查询 '目标' 与目标向量一致）"""

    def embed(self, text: str) -> list[float]:
        return [float(ord(ch)) for ch in text] or [0.0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class _BoostReranker(RerankerInterface):
    """假重排：包含 '目标' 的文档得 0.9，否则 0.1"""

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [0.9 if "目标" in doc else 0.1 for doc in documents]


def _build_retriever(neighbor_window: int = 0, min_score: float = 0.0, reranker=None) -> Retriever:
    RequestContext.clear()  # 显式无租户上下文 → 检索走 no-tenant 命名空间
    store = InMemoryVectorStore()
    texts = {
        "d1": "目标文档一",
        "d2": "目标文档二",
        "d3": "其他文档三",
    }
    emb = _FakeEmbedding()
    vectors = emb.embed_batch(list(texts.values()))
    store.add(NO_TENANT, list(texts.keys()), vectors)
    return Retriever(
        store, emb,
        reranker=reranker,
        neighbor_window=neighbor_window,
        min_score=min_score,
        document_texts=texts,
    )


def test_retriever_basic_search():
    """基础检索返回命中文本与得分"""
    retriever = _build_retriever()
    results = retriever.search("目标", top_k=2)
    assert len(results) <= 2
    assert all(r.text for r in results)  # 文本已携带
    assert all(r.id in ("d1", "d2", "d3") for r in results)


def test_retriever_rerank_orders_results():
    """重排器分数参与排序与阈值过滤"""
    retriever = _build_retriever(reranker=_BoostReranker(), min_score=0.5)
    results = retriever.search("目标", top_k=3)
    assert results  # 命中 d1/d2 得 0.9，d3 得 0.1 被过滤
    assert all(r.score >= 0.5 for r in results)
    assert all("目标" in r.text for r in results)


def test_retriever_threshold_filters():
    """阈值过滤：低于阈值的结果被剔除"""
    retriever = _build_retriever(min_score=1.0)  # 阈值 1.0，Identity 得分为 1.0 保留
    # 无重排时 Identity 得分 1.0，全部保留
    results = retriever.search("目标", top_k=3)
    assert results


def test_retriever_neighbor_expansion():
    """邻居扩展：命中块前后的相邻块被纳入"""
    store = InMemoryVectorStore()
    emb = _FakeEmbedding()
    texts = {"b1": "块一", "b2": "目标块", "b3": "块三", "b4": "块四"}
    store.add(NO_TENANT, list(texts.keys()), emb.embed_batch(list(texts.values())))
    retriever = Retriever(store, emb, neighbor_window=1, document_texts=texts)
    results = retriever.search("目标", top_k=5)
    ids = [r.id for r in results]
    assert "b2" in ids  # 命中块
    assert "b1" in ids and "b3" in ids  # 前后邻居被扩展


def test_retriever_degraded_on_error():
    """异常降级：嵌入抛错返回空列表"""
    class _BrokenEmbedding(EmbeddingProviderInterface):
        def embed(self, text: str) -> list[float]:
            raise RuntimeError("embed down")

        def embed_batch(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("embed down")

    store = InMemoryVectorStore()
    retriever = Retriever(store, _BrokenEmbedding())
    assert retriever.search("目标") == []


# ---------------------------------------------------------------------------
# 租户维度隔离（多租户规范 §2）
# ---------------------------------------------------------------------------

def test_vector_store_tenant_isolation():
    """租户隔离：同库不同 tenant 写入后互不可见（search/get/ids_in_order/delete）"""
    store = InMemoryVectorStore()
    emb = _FakeEmbedding()
    store.add("tenant-a", ["a1"], emb.embed_batch(["目标A"]))
    store.add("tenant-b", ["b1"], emb.embed_batch(["目标B"]))

    # search 只返回本租户命中，不出现他租户向量
    hits_a = store.search("tenant-a", emb.embed("目标A"), top_k=5)
    hits_b = store.search("tenant-b", emb.embed("目标A"), top_k=5)
    assert [h.id for h in hits_a] == ["a1"]
    assert [h.id for h in hits_b] == ["b1"]  # b1 是 tenant-b 唯一向量
    assert "a1" not in [h.id for h in hits_b]

    # ids_in_order / get 按租户隔离
    assert store.ids_in_order("tenant-a") == ["a1"]
    assert store.ids_in_order("tenant-b") == ["b1"]
    assert store.get("tenant-a", ["b1"]) == {}
    assert store.get("tenant-b", ["a1"]) == {}

    # delete 只作用于指定租户，不影响他租户
    store.delete("tenant-a", ["a1"])
    assert store.search("tenant-a", emb.embed("目标A"), top_k=5) == []
    assert [h.id for h in store.search("tenant-b", emb.embed("目标B"), top_k=5)] == ["b1"]


def test_retriever_tenant_context_isolated():
    """有租户上下文时检索只命中本租户数据，不跨租户命中"""
    store = InMemoryVectorStore()
    emb = _FakeEmbedding()
    store.add("tenant-a", ["a1"], emb.embed_batch(["目标A"]))
    store.add("tenant-b", ["b1"], emb.embed_batch(["目标B"]))
    retriever = Retriever(store, emb, document_texts={"a1": "目标A", "b1": "目标B"})

    RequestContext.set_tenant_id("tenant-a")
    try:
        assert [r.id for r in retriever.search("目标A")] == ["a1"]
        # 本租户命名空间内不存在 b1，即使 tenant-b 有相似内容也不返回
        assert "b1" not in [r.id for r in retriever.search("目标B")]
    finally:
        RequestContext.clear()

    RequestContext.set_tenant_id("tenant-b")
    try:
        assert [r.id for r in retriever.search("目标B")] == ["b1"]
        assert "a1" not in [r.id for r in retriever.search("目标B")]
    finally:
        RequestContext.clear()


def test_retriever_no_tenant_context_uses_no_tenant():
    """无租户上下文时检索使用 no-tenant 占位隔离"""
    RequestContext.clear()
    store = InMemoryVectorStore()
    emb = _FakeEmbedding()
    store.add(NO_TENANT, ["n1"], emb.embed_batch(["目标A"]))
    store.add("tenant-a", ["a1"], emb.embed_batch(["目标A"]))
    retriever = Retriever(store, emb, document_texts={"n1": "目标A", "a1": "目标A"})

    results = retriever.search("目标A")
    assert [r.id for r in results] == ["n1"]
    assert "a1" not in [r.id for r in results]  # tenant-a 数据不可见


def test_vector_store_tenant_optional_reads_context():
    """tenant_id 可选：缺省从请求上下文（RequestContext）读取"""
    store = InMemoryVectorStore()
    emb = _FakeEmbedding()
    RequestContext.set_tenant_id("tenant-a")
    try:
        store.add(None, ["a1"], emb.embed_batch(["目标A"]))
    finally:
        RequestContext.clear()
    hits = store.search("tenant-a", emb.embed("目标A"), top_k=5)
    assert [h.id for h in hits] == ["a1"]
    # 无租户上下文（no-tenant）检索不到 tenant-a 数据
    assert store.search(None, emb.embed("目标A"), top_k=5) == []


def test_vector_store_tenant_optional_defaults_placeholder():
    """tenant_id 可选：无上下文且不传租户 → no-tenant 占位命名空间（单租户数据收敛）"""
    RequestContext.clear()
    store = InMemoryVectorStore()
    emb = _FakeEmbedding()
    store.add(None, ["n1"], emb.embed_batch(["目标A"]))
    hits = store.search(None, emb.embed("目标A"), top_k=5)
    assert [h.id for h in hits] == ["n1"]
    # 显式 no-tenant 与缺省解析结果一致
    hits = store.search(NO_TENANT, emb.embed("目标A"), top_k=5)
    assert [h.id for h in hits] == ["n1"]
