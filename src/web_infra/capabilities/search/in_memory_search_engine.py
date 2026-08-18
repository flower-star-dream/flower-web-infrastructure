"""
内存搜索引擎（默认实现）

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 基于内存字典的全文搜索引擎（SearchEngineInterface 默认实现，测试/小规模场景）：
              简单分词（英文按单词、中文按单字）构建倒排索引，简化 BM25 打分，
              支持分页与高亮（<em> 包裹命中词）。真实大规模场景建议接入
              ElasticsearchSearchEngine（elasticsearch-dsl，搜索引擎接入计划 v0.2.0 §3.2）。
              tenant_id 可选（2026-08-18 评审调整）：显式传则按租户隔离；缺省读请求上下文
              （TenantGuard.current_tenant），再无回落 no-tenant 占位（单租户所有数据收敛同一命名空间）。
              内部按（解析后租户 + 索引名）划分命名空间（多租户规范 §2：禁止跨租户命中），
              容量上限按命名空间计数，超限淘汰最旧写入的文档（防内存无限增长）。
"""
from __future__ import annotations

import logging
import math
import re
from threading import Lock
from typing import Any

from web_infra.capabilities.db.tenant_guard import TenantGuard
from web_infra.capabilities.search.search_constant import SearchConstant
from web_infra.capabilities.search.search_engine_interface import SearchEngineInterface
from web_infra.capabilities.search.search_hit import SearchHit
from web_infra.capabilities.search.search_query import SearchQuery

logger = logging.getLogger("web_infra.capabilities.search.in_memory")

# 连续中文字符段（分词用：中文按单字切分，英文按单词切分）
_CN_SEGMENT = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """简单分词：英文按单词（小写）、中文按单字、数字按整体；用于 InMemory 倒排与高亮。

    :param text: 原始文本
    :return: 分词 token 列表（保持出现顺序，含重复）
    """
    tokens: list[str] = []
    lowered = text.lower()
    # 交替扫描：中文连续段按单字切分，其余部分按英文单词/数字切分
    for part in re.split(r"([\u4e00-\u9fff]+)", lowered):
        if not part:
            continue
        if _CN_SEGMENT.fullmatch(part):
            tokens.extend(part)
        else:
            tokens.extend(_WORD.findall(part))
    return tokens


class InMemorySearchEngine:
    """内存全文搜索引擎（SearchEngineInterface 默认实现，命名空间按 租户+索引 隔离）

    @Stateful：进程内内存存储，单实例/单进程部署，多实例需替换为 ElasticsearchSearchEngine（S1-1）。
    """

    def __init__(self, max_documents_per_tenant: int | None = None) -> None:
        """初始化内存搜索引擎。

        :param max_documents_per_tenant: 单命名空间（租户+索引）文档条数上限（None 表示不限制，默认兼容旧行为；
            生产建议配置上限，防止文档无限累积导致内存增长，参照 InMemoryVectorStore）
        """
        # 命名空间（租户+索引）→ 文档：{doc_id: document}
        self._docs: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        # 命名空间 → 倒排：{term: {doc_id: term_frequency}}
        self._terms: dict[tuple[str, str], dict[str, dict[str, int]]] = {}
        # 命名空间 → 文档 token 长度（BM25 归一化用）
        self._lengths: dict[tuple[str, str], dict[str, int]] = {}
        # 命名空间 → 写入顺序
        self._order: dict[tuple[str, str], list[str]] = {}
        self._max_documents_per_tenant = max_documents_per_tenant
        self._lock = Lock()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def create_index(
        self,
        tenant_id: str | None,
        index_name: str,
        *,
        mappings: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        """创建索引（内存实现无物理索引，幂等空操作：mappings/settings 仅校验后忽略）"""
        tenant_id = _resolve_tenant(tenant_id)
        # 校验参数合法（与 ES 实现保持一致的契约校验）
        _validate_namespace(tenant_id, index_name)

    async def delete_index(self, tenant_id: str | None, index_name: str) -> None:
        """删除索引：清空该命名空间下全部文档与倒排（幂等：不存在时静默）"""
        tenant_id = _resolve_tenant(tenant_id)
        _validate_namespace(tenant_id, index_name)
        key = (tenant_id, index_name)
        with self._lock:
            self._docs.pop(key, None)
            self._terms.pop(key, None)
            self._lengths.pop(key, None)
            self._order.pop(key, None)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    async def index_document(
        self,
        tenant_id: str | None,
        index_name: str,
        doc_id: str,
        document: dict[str, Any],
        *,
        refresh: bool = False,
    ) -> None:
        """写入/覆盖单条文档（doc_id 幂等：同名覆盖，先删旧倒排再建新倒排）"""
        tenant_id = _resolve_tenant(tenant_id)
        _validate_namespace(tenant_id, index_name)
        with self._lock:
            self._delete_doc_locked(tenant_id, index_name, doc_id)
            self._insert_doc_locked(tenant_id, index_name, doc_id, document)

    async def bulk_index(
        self,
        tenant_id: str | None,
        index_name: str,
        documents: list[dict[str, Any]],
        *,
        refresh: bool = False,
    ) -> None:
        """批量写入文档（元素必须含 id 键；缺 id 的项跳过并记录告警，不中断整批）"""
        tenant_id = _resolve_tenant(tenant_id)
        _validate_namespace(tenant_id, index_name)
        with self._lock:
            for item in documents:
                doc_id = item.get("id")
                if not doc_id:
                    logger.warning("bulk_index skipped_missing_id index=%s", index_name)
                    continue
                body = {k: v for k, v in item.items() if k != "id"}
                self._delete_doc_locked(tenant_id, index_name, str(doc_id))
                self._insert_doc_locked(tenant_id, index_name, str(doc_id), body)

    async def delete_document(
        self,
        tenant_id: str | None,
        index_name: str,
        doc_id: str,
        *,
        refresh: bool = False,
    ) -> None:
        """按文档 ID 删除（幂等：不存在时静默）"""
        tenant_id = _resolve_tenant(tenant_id)
        _validate_namespace(tenant_id, index_name)
        with self._lock:
            self._delete_doc_locked(tenant_id, index_name, doc_id)

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    async def search(self, tenant_id: str | None, query: SearchQuery) -> list[SearchHit]:
        """关键词检索：简化 BM25 打分 → 得分降序 → 分页 → 可选高亮"""
        tenant_id = _resolve_tenant(tenant_id)
        _validate_namespace(tenant_id, query.index_name)
        tokens = tokenize(query.keyword)
        if not tokens:
            return []
        key = (tenant_id, query.index_name)
        with self._lock:
            docs = self._docs.get(key, {})
            terms = self._terms.get(key, {})
            lengths = self._lengths.get(key, {})
            if not docs or not terms:
                return []
            n_docs = len(docs)
            avg_len = sum(lengths.values()) / n_docs if n_docs else 0.0
            scores: dict[str, float] = {}
            for token in tokens:
                postings = terms.get(token)
                if not postings:
                    continue
                idf = math.log(1.0 + (n_docs - len(postings) + 0.5) / (len(postings) + 0.5))
                for doc_id, tf in postings.items():
                    doc_len = lengths.get(doc_id, 0)
                    tf_norm = tf * (SearchConstant.BM25_K1 + 1) / (
                        tf + SearchConstant.BM25_K1 * (
                            1 - SearchConstant.BM25_B + SearchConstant.BM25_B * doc_len / avg_len
                        )
                    ) if avg_len else tf
                    scores[doc_id] = scores.get(doc_id, 0.0) + idf * tf_norm
            ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
            page = ranked[query.offset : query.offset + query.size]
            return [
                SearchHit(
                    id=doc_id,
                    score=round(score, 4),
                    source=docs[doc_id],
                    highlight=_make_highlight(docs[doc_id], tokens) if query.highlight else {},
                )
                for doc_id, score in page
            ]

    # ------------------------------------------------------------------
    # 内部：命名空间增删
    # ------------------------------------------------------------------

    def _insert_doc_locked(
        self, tenant_id: str, index_name: str, doc_id: str, document: dict[str, Any]
    ) -> None:
        """锁内写入：登记文档、构建倒排（含容量上限淘汰最旧）"""
        key = (tenant_id, index_name)
        data = self._docs.setdefault(key, {})
        order = self._order.setdefault(key, [])
        tokens = _collect_tokens(document)
        data[doc_id] = document
        self._lengths.setdefault(key, {})[doc_id] = len(tokens)
        if doc_id not in order:
            order.append(doc_id)
        term_map = self._terms.setdefault(key, {})
        for token in tokens:
            postings = term_map.setdefault(token, {})
            postings[doc_id] = postings.get(doc_id, 0) + 1
        # 容量上限：超限后按写入顺序淘汰最旧文档（防内存无限增长）
        if self._max_documents_per_tenant is not None and len(data) > self._max_documents_per_tenant:
            overflow = len(data) - self._max_documents_per_tenant
            for old_doc_id in order[:overflow]:
                self._delete_doc_locked(tenant_id, index_name, old_doc_id)

    def _delete_doc_locked(self, tenant_id: str, index_name: str, doc_id: str) -> None:
        """锁内删除：移除文档并清理倒排（不存在时静默）"""
        key = (tenant_id, index_name)
        data = self._docs.get(key)
        if not data or doc_id not in data:
            return
        document = data.pop(doc_id)
        tokens = _collect_tokens(document)
        term_map = self._terms.get(key, {})
        for token in tokens:
            postings = term_map.get(token)
            if not postings:
                continue
            postings.pop(doc_id, None)
            if not postings:
                term_map.pop(token, None)
        lengths = self._lengths.get(key)
        if lengths:
            lengths.pop(doc_id, None)
        order = self._order.get(key)
        if order and doc_id in order:
            order.remove(doc_id)


# ----------------------------------------------------------------------
# 模块级工具（租户解析 / 分词 / 高亮 / 命名空间校验）
# ----------------------------------------------------------------------


def _resolve_tenant(tenant_id: str | None) -> str:
    """解析租户标识：显式传入优先；否则从请求上下文读取；再无则 no-tenant 占位（多租户规范 §2）"""
    return tenant_id or TenantGuard.current_tenant()


def _collect_tokens(document: dict[str, Any]) -> list[str]:
    """收集文档内全部字符串字段的 token（可检索字段为 str 值）"""
    tokens: list[str] = []
    for value in document.values():
        if isinstance(value, str):
            tokens.extend(tokenize(value))
    return tokens


def _make_highlight(document: dict[str, Any], tokens: list[str]) -> dict[str, list[str]]:
    """生成高亮片段：对文档内全部字符串字段，将命中 token 包裹 <em> 标签。

    中文单字分词下相邻单字各自高亮（如 <em>框</em><em>架</em>），
    为简单默认实现，生产环境建议接入 ES 实现（按词/短语高亮更自然）。
    """
    if not tokens:
        return {}
    unique = list(dict.fromkeys(tokens))
    highlight: dict[str, list[str]] = {}
    for field, value in document.items():
        if not isinstance(value, str):
            continue
        highlighted = value
        for token in unique:
            highlighted = re.sub(
                re.escape(token),
                f"{SearchConstant.HIGHLIGHT_PRE_TAG}\\g<0>{SearchConstant.HIGHLIGHT_POST_TAG}",
                highlighted,
                flags=re.IGNORECASE,
            )
        if highlighted != value:
            highlight[field] = [highlighted]
    return highlight


def _validate_namespace(tenant_id: str, index_name: str) -> None:
    """校验命名空间参数：禁止空值与下划线（避免 ES 索引名拼接歧义，见 ElasticsearchSearchEngine._index_name）"""
    if not tenant_id or not index_name:
        raise ValueError("tenant_id 与 index_name 均不能为空")
    if "_" in tenant_id or "_" in index_name:
        raise ValueError("tenant_id 与 index_name 不能包含下划线 '_'（命名空间分隔符保留）")
