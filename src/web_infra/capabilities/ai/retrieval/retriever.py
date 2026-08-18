"""
检索器

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 统一检索流程（AI 规范 §11）：向量召回 → 邻居扩展（可选）→ Rerank → 相似度阈值过滤；
              向量库/嵌入异常时降级返回空列表（保证主流程可用）。
              检索遵守多租户规范 §2：从请求上下文读取当前租户传入向量库（tenant_id 可选，
              2026-08-18 评审调整：无租户时由向量存储实现回落 no-tenant 占位），禁止跨租户命中知识库内容。
"""
from __future__ import annotations

import logging

from web_infra.infra.context import RequestContext
from web_infra.capabilities.ai.retrieval.embedding_provider import EmbeddingProviderInterface
from web_infra.capabilities.ai.retrieval.identity_reranker import IdentityReranker
from web_infra.capabilities.ai.retrieval.reranker import RerankerInterface
from web_infra.capabilities.ai.retrieval.retrieval_result import RetrievalResult
from web_infra.capabilities.ai.retrieval.vector_store_interface import VectorStoreInterface

logger = logging.getLogger("web_infra.capabilities.ai.retrieval")


class Retriever:
    """检索器：召回 → 邻居扩展 → 重排 → 阈值过滤（异常降级为空）"""

    def __init__(
        self,
        vector_store: VectorStoreInterface,
        embedding_provider: EmbeddingProviderInterface,
        reranker: RerankerInterface | None = None,
        neighbor_window: int = 0,
        min_score: float = 0.75,
        document_texts: dict[str, str] | None = None,
    ) -> None:
        """初始化检索器。

        :param vector_store: 向量存储
        :param embedding_provider: 嵌入供应商
        :param reranker: 重排器（默认 IdentityReranker 不重排）
        :param neighbor_window: 邻居扩展窗口（0 不扩展；n 表示命中块前后各扩展 n 个相邻块）
        :param min_score: 相似度阈值（AI-6：建议余弦 ≥0.75，Rerank 得分低于该值的命中被过滤；
              默认 0.75，调用方显式传参时尊重其值；全部低于阈值时降级返回空列表）
        :param document_texts: 向量 ID → 文档文本 映射（供结果携带文本；缺失时以 ID 兜底）
        """
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider
        self._reranker = reranker or IdentityReranker()
        self._neighbor_window = neighbor_window
        self._min_score = min_score
        self._document_texts = document_texts or {}

    def search(self, query: str, top_k: int = 3) -> list[RetrievalResult]:
        """执行检索：召回 → 邻居扩展 → 重排 → 阈值过滤。

        :param query: 查询文本
        :param top_k: 返回结果数（邻居扩展后按最终得分截断）
        :return: 检索结果列表；异常时返回空列表（降级）
        """
        try:
            # 多租户隔离：从请求上下文读取当前租户（无租户时由向量存储实现回落 no-tenant 占位）
            tenant_id = RequestContext.get_tenant_id()
            query_vector = self._embedding_provider.embed(query)
            hits = self._vector_store.search(tenant_id, query_vector, top_k=top_k)
            ids = [hit.id for hit in hits]

            # 邻居扩展：按写入顺序取命中块前后 window 个相邻块
            if self._neighbor_window > 0:
                ids = self._expand_neighbors(tenant_id, ids)

            # 文本化 + 重排打分
            documents = [self._document_texts.get(vid, vid) for vid in ids]
            scores = self._reranker.rerank(query, documents)

            results: list[RetrievalResult] = []
            for vid, doc, score in zip(ids, documents, scores):
                if score < self._min_score:
                    continue
                results.append(RetrievalResult(id=vid, text=doc, score=round(score, 4)))
            # AI-6：全部命中低于阈值 → 低相关降级为纯生成（返回空列表并告警，不阻断主流程）
            if not results and scores:
                logger.warning(
                    "retrieval_low_relevance query=%s best_score=%s threshold=%s → 低相关降级为纯生成",
                    query, round(max(scores), 4), self._min_score,
                )
            # 按重排得分降序，截断 top_k
            results.sort(key=lambda r: r.score, reverse=True)
            return results[:top_k]
        except Exception as e:  # 检索失败降级：记录日志返回空，不阻断主流程
            logger.warning("retrieval_degraded query=%s error=%s", query, str(e))
            return []

    def _expand_neighbors(self, tenant_id: str, hit_ids: list[str]) -> list[str]:
        """按向量存储写入顺序，扩展命中块的前后邻居（窗口为 neighbor_window）"""
        order = self._vector_store.ids_in_order(tenant_id)
        position = {vid: i for i, vid in enumerate(order)}
        expanded: list[str] = []
        for vid in hit_ids:
            pos = position.get(vid)
            if pos is None:
                continue
            start = max(0, pos - self._neighbor_window)
            end = min(len(order), pos + self._neighbor_window + 1)
            for neighbor in order[start:end]:
                if neighbor not in expanded:
                    expanded.append(neighbor)
        return expanded
