# RAG 检索与向量库

> 把文档「切块 → 向量化 → 入库 → 检索」串起来，让大模型回答基于你的知识库而不是凭空生成——
> 本文讲透 `web_infra.capabilities.ai.retrieval` 的切片、Embedding、向量存储、召回/重排/阈值过滤全链路与租户隔离语义。

---

## 目录

- [1. 是什么](#1-是什么)
- [2. 何时用](#2-何时用)
- [3. RAG 全流程](#3-rag-全流程)
- [4. 文档切片 MarkdownChunker](#4-文档切片-markdownchunker)
- [5. Embedding](#5-embedding)
- [6. 向量存储](#6-向量存储)
- [7. 检索器 Retriever](#7-检索器-retriever)
- [8. 租户命名空间隔离](#8-租户命名空间隔离)
- [9. ElasticsearchVectorStore 索引设计](#9-elasticsearchvectorstore-索引设计)
- [10. 数据模型](#10-数据模型)
- [11. es extra 依赖](#11-es-extra-依赖)
- [12. 完整示例：建库 → 切分 → 入库 → 检索](#12-完整示例建库--切分--入库--检索)
- [13. RAG 问答端到端示例（检索 + 模型网关）](#13-rag-问答端到端示例检索--模型网关)
- [14. 常见坑](#14-常见坑)

## 1. 是什么

`web_infra.capabilities.ai.retrieval` 提供完整的检索增强生成（RAG）基础设施，按《AI 规范 §11》实现：

| 环节 | 默认实现 | 生产实现 | 扩展点（SPI） |
| ---- | -------- | -------- | ------------- |
| 文档切片 | `MarkdownChunker`（标题分组/空行分段/代码块表格原子块） | 同左，或按文档类型新增 | `DocumentChunkerInterface` |
| 向量化 | `HashEmbeddingProvider`（确定性哈希特征，**无语义质量**，仅兜底） | 真实模型（bge-m3 / OpenAI 兼容 Embedding 服务） | `EmbeddingProviderInterface` |
| 向量存储 | `InMemoryVectorStore`（线性扫描余弦相似度） | `ElasticsearchVectorStore`（dense_vector + kNN，需 `[es]` extra） | `VectorStoreInterface` |
| 重排 | `IdentityReranker`（原样返回，得分 1.0） | CrossEncoder 等模型 | `RerankerInterface` |
| 检索编排 | `Retriever`（召回 → 邻居扩展 → 重排 → 阈值过滤 → 异常降级） | 同左，注入生产组件即可 | — |

检索结果可直接拼入大模型 Prompt（配合 [15-AI模型网关.md](./15-AI模型网关.md) 的 `PromptAssembler`），也可独立作为知识库问答/文档检索能力。

## 2. 何时用

- 需要对私有知识库 / 业务文档做「基于内容的问答」：先检索相关片段，再让大模型基于片段回答；
- 需要批量文档入库（Markdown 为主）、按相似度检索、按相关性阈值控制"是否采用检索结果"；
- 单机/测试/演示：内存全链路开箱即用（`HashEmbeddingProvider` + `InMemoryVectorStore`），无外部依赖；
- 生产：接入真实 Embedding 模型 + Elasticsearch（kNN 检索）即可扩展，检索编排代码零改动。

## 3. RAG 全流程

```
原始文档
  → MarkdownChunker.chunk(doc)             # 切块：标题分组、空行分段、代码块/表格原子块
  → EmbeddingProvider.embed_batch(texts)   # 向量化（文本 ↔ 向量一一对应）
  → VectorStore.add(tenant, ids, vectors)  # 入库（按租户命名空间隔离）
  → Retriever.search(query, top_k)         # 检索：
      1) embed(query)                       #   查询向量化（与入库同一 Embedding 模型，维度必须一致）
      2) vector_store.search(tenant, qv, top_k)   # 向量召回
      3) neighbor_window > 0 时邻居扩展     #   按写入顺序取命中块前后 window 个相邻块
      4) Reranker.rerank(query, docs)       #   重排打分（默认 Identity 保持原序）
      5) score < min_score 过滤             #   默认阈值 0.75
      6) 全部低于阈值 → 低相关降级为纯生成   #   返回空列表并告警，不阻断主流程
      7) 按得分降序截断 top_k 返回 RetrievalResult
```

## 4. 文档切片 MarkdownChunker

`MarkdownChunker.chunk(document) -> list[Chunk]` 按结构块切分（默认实现，HTML/PDF 等经 `DocumentChunkerInterface` 扩展）：

- **标题分组**：`#{1,6}` 标题刷新段落，后续正文/原子块携带最近标题上下文（`Chunk.heading` / `Chunk.level`）；
- **空行分段**：正文按空行分隔累积成段，空行本身不写入切片；
- **代码块原子块**：` ``` ` 包裹内容整块为单一 Chunk，不拆分（代码语义完整性）；
- **表格原子块**：`|` 开头且下一行是分隔行（`| --- |`）判定为表格块，整表为单一 Chunk；
- 每个 Chunk 携带**顺序号** `order`（单调递增，供邻居扩展定位相邻块）。

```python
from web_infra.capabilities.ai import MarkdownChunker

chunks = MarkdownChunker().chunk("""
# 引言
这是引言内容。

# 方法
```python
x = 1
```

| 列A | 列B |
| --- | --- |
| 1   | 2   |
""")
# 结果：引言段落(1) + 方法标题下代码块(2) + 表格(3)，各带 heading 与 order
```

## 5. Embedding

### 5.1 EmbeddingProviderInterface

```python
class EmbeddingProviderInterface(ABC):
    def embed(self, text: str) -> list[float]: ...            # 单段文本 → 向量
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...  # 批量，顺序与入参一致
```

### 5.2 HashEmbeddingProvider（默认兜底）

基于**稳定哈希特征**的本地实现（`dimension` 默认 256，L2 归一化）：

- 分词：英文单词/数字/下划线按词、中文按单字（统一小写，保证确定性）；
- 每 token 计算 crc32 映射到 `[0, dimension)` 索引累加，哈希高位决定累加符号（防向量退化），L2 归一化；空文本返回全 0 向量；
- **只保证「同文本向量稳定可比较」，不具备语义质量**——同义词/改写不相似，不可用于语义排序；生产必须注入真实模型（bge-m3 / OpenAI 兼容 Embedding 服务，实现同一接口即可，检索编排代码零改动）。

### 5.3 生产接入示例：OpenAI 兼容 Embedding 服务

接入真实 Embedding 模型只需实现 `EmbeddingProviderInterface`。以下示例复用模型网关的供应商抽象
（`EmbeddingRequest` / `EmbeddingResponse`，见 [15-AI模型网关.md](./15-AI模型网关.md) §4），把网络调用交给
`OpenAICompatibleProvider.embedding`，本类只做批量编排：

```python
from web_infra.capabilities.ai import (
    EmbeddingRequest, EmbeddingResponse, ModelConfig, OpenAICompatibleProvider,
)
from web_infra.capabilities.ai.retrieval import EmbeddingProviderInterface

class OpenAiCompatibleEmbeddingProvider(EmbeddingProviderInterface):
    """基于 OpenAI 兼容供应商的 Embedding 实现（生产接入 bge-m3 / text-embedding-* 等）"""

    def __init__(self, config: ModelConfig) -> None:
        # config 指向一个 Embedding 模型配置（provider=openai_compatible）
        self._config = config
        self._provider = OpenAICompatibleProvider(config)

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # OpenAICompatibleProvider.embedding 是 async 方法，同步封装需事件循环（业务在 async 内调用）
        import asyncio
        request = EmbeddingRequest(model=self._config.model_code, input=texts)
        return asyncio.run(self._provider.embedding(request)).embeddings
```

> 提示：更推荐在 async 业务代码里直接 `await provider.embedding(EmbeddingRequest(...))`（网关 `embed` 入口
> 自带路由/配额/权限校验，见 [15-AI模型网关.md](./15-AI模型网关.md) §7.3）；`Retriever.search` 的 `embed()`
> 为同步接口，若生产 Embedding 是异步实现，可在子线程/事件循环中桥接，或在检索器外层自行封装 async 版本。

## 6. 向量存储

### 6.1 VectorStoreInterface

```python
class VectorStoreInterface(ABC):
    def add(self, tenant_id, ids, vectors) -> None                          # 批量写入（ID 与向量一一对应）
    def delete(self, tenant_id, ids) -> None                                # 批量删除（幂等）
    def search(self, tenant_id, query_vector, top_k) -> list[VectorHit]     # 相似度检索（得分越大越相似）
    def get(self, tenant_id, ids) -> dict[str, list[float]]                 # 按 ID 取回（邻居扩展用）
    def ids_in_order(self, tenant_id) -> list[str]                          # 按写入顺序返回全部 ID
```

`tenant_id` 为可选参数：显式传则隔离；缺省从请求上下文（`TenantGuard.current_tenant()`）读取；再无回落 `no-tenant` 占位（多租户规范 §2，单租户系统所有数据收敛同一命名空间）。

### 6.2 InMemoryVectorStore（默认实现）

- 内部按租户命名空间存储（`{tenant_id: {vector_id: vector}}` + 写入顺序）；
- 检索为**线性扫描余弦相似度**（`_cosine_similarity`，维度不一致返回 0.0），适合测试/小规模；
- `max_vectors_per_tenant` 可设单租户条数上限，超限按写入顺序淘汰最旧（防内存无限增长）；
- `@Stateful`：进程内内存存储，多实例需替换为分布式实现。

### 6.3 ElasticsearchVectorStore（生产实现）

基于官方 `elasticsearch-dsl` 的 `VectorStoreInterface` 实现：`dense_vector` 字段 + ES 8 原生 kNN 检索（详见 §9）。

## 7. 检索器 Retriever

### 7.1 构造参数

```python
Retriever(
    vector_store,               # 向量存储（必选）
    embedding_provider,         # 嵌入供应商（必选）
    reranker=None,              # 默认 IdentityReranker（不重排）
    neighbor_window=0,          # 邻居扩展窗口：0 不扩展；n 表示命中块前后各扩展 n 个相邻块
    min_score=0.75,             # 相似度阈值（AI-6：建议余弦 ≥0.75；Rerank 得分低于该值被过滤）
    document_texts=None,        # 向量 ID → 文档文本 映射（结果携带文本；缺失以 ID 兜底）
)
```

### 7.2 search 调用时序

```
Retriever.search(query, top_k=3)
  → tenant_id = RequestContext.get_tenant_id()      # 多租户隔离：缺省读请求上下文
  → query_vector = embedding_provider.embed(query)
  → hits = vector_store.search(tenant_id, query_vector, top_k=top_k)   # 向量召回
  → neighbor_window > 0: _expand_neighbors(tenant_id, ids)             # 按写入顺序扩展相邻块（去重保序）
  → documents = [document_texts.get(vid, vid) for vid in ids]
  → scores = reranker.rerank(query, documents)                          # 重排打分
  → score < min_score 的命中被过滤（AI-6 阈值过滤）
  → 全部低于阈值 → logger.warning 低相关降级为纯生成（返回空列表，不阻断主流程）
  → 按得分降序排序，截断 top_k，返回 list[RetrievalResult]
```

- **邻居扩展**：命中块前后各取 `window` 个相邻块（借助 `ids_in_order` 的写入顺序定位），适合切片过碎导致语义被切散的场景；
- **阈值过滤**：默认 `min_score=0.75`（调用方显式传参时尊重其值）。注意：无重排时 `IdentityReranker` 得分恒为 1.0，**阈值默认不会过滤任何命中**——阈值过滤真正生效需要注入真实重排器（得分落在 [0,1]）；
- **异常降级**：向量库/嵌入异常时 `except Exception` 捕获，返回空列表并告警（保证主流程可用）。

## 8. 租户命名空间隔离

- 入库 `add(tenant_id, ...)` 与检索 `search(tenant_id, ...)` 均按（解析后的）租户划分命名空间，**禁止跨租户命中知识库内容**（多租户规范 §2）；
- 租户解析优先级：显式传参 > `TenantGuard.current_tenant()`（请求上下文）> `no-tenant` 占位；
- ES 实现以**真实索引**隔离：`{index_prefix}_{tenant}_vector`，`tenant_id` 含下划线会抛 ValueError（分隔符保留）；
- 单租户系统：无需传租户，所有数据收敛 `no-tenant` 命名空间，隔离退化为全局共享。

## 9. ElasticsearchVectorStore 索引设计

```python
ElasticsearchVectorStore(
    hosts=["http://localhost:9200"],   # 列表或逗号分隔字符串
    index_prefix="web",                # 真实索引名 {prefix}_{tenant}_vector
    username="", password="",          # 空表示无需认证
    verify_certs=True,                 # TLS 证书校验（生产默认开启）
    dims=768,                          # 向量维度（与嵌入模型对齐，默认对齐 sentence-transformers all-MiniLM 系）
    num_candidates=100,                # kNN 候选数（建议 ≥ 10*top_k）
    auto_create_index=True,            # 写入/检索前自动幂等创建索引
)
```

索引设计要点：

- **索引名**：`{index_prefix}_{tenant_id}_vector`，mapping 含 `vector`（`dense_vector`, `dims=768`）与 `vector_id`（`keyword`）两字段；
- **settings**：`number_of_shards: 1`、`number_of_replicas: 0`；
- **kNN 检索**：`Search.extra(knn={field, query_vector, k: top_k, num_candidates})`，得分即 `hit.meta.score`；
- **幂等创建**：`indices.create(ignore_status=[400])` 忽略已存在冲突（resource_already_exists_exception），失败仅告警不阻断；
- **批量写入**：`bulk`（`{"index": {"_index": name, "_id": vid}}` + `{"vector": [...]}`），ID 冲突覆盖；
- **ids_in_order**：ES 不保证写入顺序语义，按 `_id` 升序返回（能力有限）；业务如需按写入顺序扩展邻居，可自定义 ID 编码（如时间序雪花 ID）保证 `_id` 升序即写入序；
- **close()**：释放底层 ES 客户端连接（应用停机/测试收尾调用）。

## 10. 数据模型

| 模型 | 字段 | 说明 |
| ---- | ---- | ---- |
| `Chunk` | `text` / `heading` / `level` / `order` | 文档切片：文本 + 所属最近标题 + 层级 + 顺序号 |
| `VectorHit` | `id` / `score` / `vector` | 向量命中项：ID + 相似度得分（越大越相似）+ 向量值 |
| `RetrievalResult` | `id` / `text` / `score` | 最终检索结果：文档/切片 ID + 文本 + 相似度得分 |

## 11. es extra 依赖

`ElasticsearchVectorStore` 依赖 **es extra**（`elasticsearch-dsl>=8.0`，自动携带 `elasticsearch-py`）：

```bash
pip install "flower-web-infrastructure[es]"
```

**延迟导入**：未安装 es extra 时 `import` 本模块不报错，**构造实例**才加载并抛出安装提示（`ImportError: ... pip install 'flower-web-infrastructure[es]'`）。`InMemoryVectorStore` / `HashEmbeddingProvider` / `Retriever` 均无该依赖，内存链路开箱即用。

## 12. 完整示例：建库 → 切分 → 入库 → 检索

```python
import asyncio

from web_infra.capabilities.ai import (
    MarkdownChunker, HashEmbeddingProvider, InMemoryVectorStore, Retriever,
)

async def main() -> None:
    # 1) 建库组件：默认 Embedding（256 维）+ 内存向量库
    embedding = HashEmbeddingProvider(dimension=256)
    store = InMemoryVectorStore(max_vectors_per_tenant=10_000)

    # 2) 切分文档
    docs = {
        "doc-1": "# 订单流程\n下单后 30 分钟内可申请取消。\n\n# 退款规则\n未发货订单全额退款。",
        "doc-2": "# 会员权益\n黄金会员享免运费。",
    }
    all_chunks: list[tuple[str, str]] = []   # (chunk_id, text)
    for doc_id, markdown in docs.items():
        for chunk in MarkdownChunker().chunk(markdown):
            all_chunks.append((f"{doc_id}#{chunk.order}", chunk.text))

    # 3) 向量化 + 入库（同租户命名空间；单租户可不传租户，回落 no-tenant）
    ids = [cid for cid, _ in all_chunks]
    texts = [text for _, text in all_chunks]
    vectors = embedding.embed_batch(texts)
    store.add("t1", ids, vectors)

    # 4) 检索（ID → 文本 映射，供结果携带原文）
    retriever = Retriever(
        store, embedding,
        neighbor_window=0,
        min_score=0.0,                        # 兜底演示：哈希向量相似度低，显式放开阈值
        document_texts=dict(all_chunks),
    )
    results = retriever.search("退款规则是什么", top_k=2)
    for r in results:
        print(r.id, round(r.score, 4), r.text)
    # 生产提示：HashEmbeddingProvider 无语义质量，应注入真实 Embedding 模型
    #（如 OpenAI 兼容服务实现 EmbeddingProviderInterface），并将 min_score 恢复默认 0.75。

    # 5) 生产切换 ES 向量库（注入真实嵌入模型，维度 dims 对齐）：
    # store = ElasticsearchVectorStore(hosts=["http://localhost:9200"], dims=768)
    # retriever = Retriever(store, real_embedding, min_score=0.75, document_texts=doc_texts)

asyncio.run(main())
```

检索结果拼入大模型 Prompt 的推荐姿势（注入防护，见 [15-AI模型网关.md](./15-AI模型网关.md) §8）：

```python
from web_infra.capabilities.ai import PromptAssembler

context = "\n\n".join(r.text for r in results)
messages = PromptAssembler().assemble_with_template(
    template="你是客服助手。请仅依据以下资料回答，资料不足请说明：\n{context}",
    variables={"context": context},
    user_input=query,
)
```

## 13. RAG 问答端到端示例（检索 + 模型网关）

把检索结果拼入 Prompt 走模型网关，即完整的 RAG 问答链路（检索 → 组装 → 生成）。完整可用骨架：

```python
import asyncio

from web_infra.capabilities.ai import (
    ChatMessage, ChatRequest, ChatRole, MarkdownChunker, HashEmbeddingProvider,
    InMemoryVectorStore, PromptAssembler, Retriever,
)
from web_infra.capabilities.ai.model_gateway import ModelGateway, ModelRouter, RouteEntry


def build_knowledge_base() -> tuple[Retriever, dict[str, str]]:
    """建库：切分 → 向量化 → 入库（此处用内存实现演示；生产换真实 Embedding + ES 向量库）"""
    embedding = HashEmbeddingProvider(dimension=256)
    store = InMemoryVectorStore()
    chunks: list[tuple[str, str]] = []
    docs = {
        "doc-1": "# 退款规则\n未发货订单可在付款后 30 分钟内全额退款。",
    }
    for doc_id, markdown in docs.items():
        for chunk in MarkdownChunker().chunk(markdown):
            chunks.append((f"{doc_id}#{chunk.order}", chunk.text))
    store.add("t1", [cid for cid, _ in chunks], embedding.embed_batch([t for _, t in chunks]))
    retriever = Retriever(store, embedding, min_score=0.0, document_texts=dict(chunks))
    return retriever, dict(chunks)


async def rag_answer(query: str, retriever: Retriever, gateway: ModelGateway) -> str:
    """检索 → 组装 Prompt → 网关生成（网关含路由/降级/配额/审核等横切，见 15-AI模型网关.md）"""
    results = retriever.search(query, top_k=3)
    messages = PromptAssembler().assemble_with_template(
        template="你是客服助手。请仅依据以下资料回答，资料不足请说明：\n{context}",
        variables={"context": "\n\n".join(r.text for r in results)},
        user_input=query,
    )
    resp = await gateway.chat(
        ChatRequest(model="deepseek-chat", messages=messages),
        scene="rag",                       # 路由场景：yml 中配置 rag 场景的主备模型
        tenant_id="t1",
        user_id="u1",
    )
    return resp.message.content


async def main() -> None:
    retriever, _ = build_knowledge_base()
    # 生产网关通常来自 create_app 装配的 app.state.ai；此处演示手工组装
    gateway = ModelGateway(ModelRouter({"rag": RouteEntry(primary="deepseek-chat")}))
    answer = await rag_answer("订单还能退款吗？", retriever, gateway)
    print(answer)

asyncio.run(main())
```

要点：

- `min_score` 默认 0.75 是「低相关降级为纯生成」的开关：检索全部低于阈值时 `Retriever` 返回空列表并告警，此时 `context` 为空，模型会回答"资料不足"——这正是 RAG 避免幻觉的正确姿势；
- 生产切 ES 向量库 + 真实 Embedding 后，`build_knowledge_base` 内部实现替换即可，`rag_answer` 零改动；
- 网关自动完成场景路由（`rag` 场景主备）、输入/输出内容审核、配额、缓存（注入后）等横切逻辑，见 [15-AI模型网关.md](./15-AI模型网关.md) §7。

## 14. 常见坑

- **HashEmbeddingProvider 只能兜底**：它没有语义质量（同义词不相似），演示/自测可把 `min_score` 调低或设 0，生产务必注入真实 Embedding 模型，否则阈值过滤会误杀全部命中；
- **Embedding 维度不一致**：入库向量与查询向量必须同维度（`dims` 与模型对齐）；`InMemoryVectorStore` 对维度不一致返回 0.0 相似度，表现为搜不到；
- **IdentityReranker 得分恒 1.0**：无重排器时默认阈值 0.75 不会过滤任何命中——需要阈值过滤就注入真实 `RerankerInterface`；
- **邻居扩展依赖写入顺序**：ES 实现按 `_id` 升序近似写入序，需要精确顺序请自定义 ID 编码；内存实现严格按写入顺序；
- **租户隔离靠解析后的租户**：`tenant_id` 缺省读请求上下文，多租户下忘记传参会默认落到当前请求租户（通常正确），但要确认请求上下文已注入租户；
- **未安装 `[es]` 时构造 ES 向量库抛 ImportError**：报错信息会给出安装命令，属预期行为（延迟导入设计）。

相关阅读：[15-AI模型网关.md](./15-AI模型网关.md)（Prompt 组装 / Embedding 供应商接入网关）、[17-搜索引擎.md](./17-搜索引擎.md)（全文检索 `app.search`，与向量检索互补）、[SPI-Extensions.md §20.3](../SPI-Extensions.md#203-向量检索接入elasticsearchvectorstore)。
