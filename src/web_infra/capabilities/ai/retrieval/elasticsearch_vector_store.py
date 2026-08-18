"""
Elasticsearch 向量存储（生产实现）

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 基于官方 elasticsearch-dsl 的向量存储实现（VectorStoreInterface，
              搜索引擎接入计划 v0.2.0 §3.3）：dense_vector 字段 + ES 8 原生 kNN 检索。
              真实索引名按 {index_prefix}_{tenant_id}_vector 隔离（多租户规范 §2：禁止跨租户命中），
              向量维度 dims 与嵌入模型对齐（如 sentence-transformers 768 维）。
              tenant_id 可选（2026-08-18 评审调整，与 SearchEngineInterface 一致）：显式传则按租户隔离；
              缺省读请求上下文（TenantGuard.current_tenant），再无回落 no-tenant 占位。
              依赖 es extra（elasticsearch-dsl>=8.0，自动携带 elasticsearch-py）：
              延迟导入，未安装 es extra 时导入本模块不报错，构造实例才加载并给出安装提示。
              与 Retriever / EmbeddingProviderInterface 组装方式与 InMemoryVectorStore 一致，注入即用，
              不改动 retriever.py（检索流程复用既有编排）。
"""
from __future__ import annotations

import logging
from typing import Any

from web_infra.capabilities.ai.retrieval.vector_hit import VectorHit
from web_infra.capabilities.ai.retrieval.vector_store_interface import VectorStoreInterface
from web_infra.capabilities.db.tenant_guard import TenantGuard

logger = logging.getLogger("web_infra.capabilities.ai.retrieval.elasticsearch")

# 向量字段名（索引 mapping 中 dense_vector 字段与 ID 字段）
_VECTOR_FIELD = "vector"
_ID_FIELD = "vector_id"


class ElasticsearchVectorStore(VectorStoreInterface):
    """Elasticsearch 向量存储（VectorStoreInterface 生产实现，dense_vector + kNN，租户前缀隔离索引）"""

    def __init__(
        self,
        *,
        hosts: list[str] | str | None = None,
        index_prefix: str = "web",
        username: str = "",
        password: str = "",
        verify_certs: bool = True,
        dims: int = 768,
        num_candidates: int = 100,
        auto_create_index: bool = True,
        client: Any | None = None,
    ) -> None:
        """初始化 ES 向量存储。

        :param hosts: ES 节点地址（列表或逗号分隔字符串；注入 client 时可不传）
        :param index_prefix: 真实索引名前缀（{prefix}_{tenant}_vector）
        :param username/password: 账号密码（空表示无需认证）
        :param verify_certs: TLS 证书校验（生产默认开启）
        :param dims: 向量维度（与嵌入模型对齐，默认 768 对齐 sentence-transformers all-MiniLM 系）
        :param num_candidates: kNN 候选数（ES kNN 查询 num_candidates，建议 ≥ 10*top_k）
        :param auto_create_index: 写入/检索前自动幂等创建索引（默认开启）
        :param client: 注入 Elasticsearch 实例（测试用；缺省按 hosts 自动创建）
        :raises ImportError: 未安装 es extra（elasticsearch-dsl）
        :raises ValueError: 未注入 client 且 hosts 为空
        """
        self._index_prefix = index_prefix
        self._dims = dims
        self._num_candidates = num_candidates
        self._auto_create_index = auto_create_index
        if client is not None:
            self._client = client
            return
        if not hosts:
            raise ValueError("hosts 不能为空（未注入 client 时需提供 ES 节点地址）")
        try:
            from elasticsearch import Elasticsearch
        except ImportError as exc:  # 延迟导入：未安装 es extra 时给出明确安装指引
            raise ImportError(
                "ElasticsearchVectorStore 需要安装 es extra：pip install 'flower-web-infrastructure[es]'"
            ) from exc
        kwargs: dict[str, Any] = {"verify_certs": verify_certs}
        if username:
            kwargs["basic_auth"] = (username, password)
        self._client = Elasticsearch(hosts=hosts, **kwargs)

    # ------------------------------------------------------------------
    # VectorStoreInterface
    # ------------------------------------------------------------------

    def add(self, tenant_id: str | None, ids: list[str], vectors: list[list[float]]) -> None:
        """批量写入向量（仅写入指定租户命名空间；bulk index，ID 冲突覆盖）"""
        if len(ids) != len(vectors):
            raise ValueError("ids 与 vectors 长度不一致")
        tenant_id = self._resolve_tenant(tenant_id)
        name = self._ensure_index(tenant_id)
        operations: list[dict[str, Any]] = []
        for vid, vector in zip(ids, vectors):
            operations.append({"index": {"_index": name, "_id": vid}})
            operations.append({_VECTOR_FIELD: vector})
        self._client.bulk(operations=operations)

    def delete(self, tenant_id: str | None, ids: list[str]) -> None:
        """批量删除指定租户下的向量（幂等：不存在的 ID 忽略）"""
        tenant_id = self._resolve_tenant(tenant_id)
        name = self._index_name(tenant_id)
        if not self._index_exists(name):
            return
        operations = [{"delete": {"_index": name, "_id": vid}} for vid in ids]
        self._client.bulk(operations=operations)

    def search(self, tenant_id: str | None, query_vector: list[float], top_k: int) -> list[VectorHit]:
        """kNN 检索指定租户命名空间内 top_k 个命中（得分越大越相似，ES 8 原生 knn 查询）"""
        from elasticsearch_dsl import Search

        tenant_id = self._resolve_tenant(tenant_id)
        name = self._ensure_index(tenant_id)
        s = Search(using=self._client, index=name)
        s = s.extra(
            knn={
                "field": _VECTOR_FIELD,
                "query_vector": query_vector,
                "k": top_k,
                "num_candidates": self._num_candidates,
            }
        )
        response = s.execute()
        hits: list[VectorHit] = []
        for hit in response.hits:
            source = hit.to_dict()
            hits.append(
                VectorHit(
                    id=hit.meta.id,
                    score=hit.meta.score if hit.meta.score is not None else 0.0,
                    vector=source.get(_VECTOR_FIELD, []),
                )
            )
        return hits

    def get(self, tenant_id: str | None, ids: list[str]) -> dict[str, list[float]]:
        """按 ID 取回指定租户下的向量（mget；未找到的 ID 不返回）"""
        tenant_id = self._resolve_tenant(tenant_id)
        name = self._index_name(tenant_id)
        if not ids:
            return {}
        if not self._index_exists(name):
            return {}
        response = self._client.mget(index=name, ids=ids)
        result: dict[str, list[float]] = {}
        for doc in response.get("docs", []):
            if doc.get("found"):
                source = doc.get("_source") or {}
                result[doc["_id"]] = source.get(_VECTOR_FIELD, [])
        return result

    def ids_in_order(self, tenant_id: str | None) -> list[str]:
        """按 _id 升序返回指定租户下全部向量 ID（邻居扩展定位相邻块用）。

        注意：ES 不保证写入顺序语义，此处按 _id 升序排列（能力有限）；
        业务如需按写入顺序扩展邻居，可自定义 ID 编码（如时间序雪花 ID）保证 _id 升序即写入序。
        """
        tenant_id = self._resolve_tenant(tenant_id)
        name = self._index_name(tenant_id)
        if not self._index_exists(name):
            return []
        response = self._client.search(index=name, size=10000, _source=False, sort=[_ID_FIELD])
        return [hit["_id"] for hit in response.body.get("hits", {}).get("hits", [])]

    # ------------------------------------------------------------------
    # 连接生命周期
    # ------------------------------------------------------------------

    def close(self) -> None:
        """关闭底层 ES 客户端连接（应用停机/测试收尾调用）"""
        try:
            self._client.close()
        except Exception as exc:
            logger.warning("elasticsearch_vector_close_failed error=%s", exc)

    # ------------------------------------------------------------------
    # 内部：租户解析 / 索引命名与隔离
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_tenant(tenant_id: str | None) -> str:
        """解析租户标识：显式传入优先；否则从请求上下文读取；再无则 no-tenant 占位（多租户规范 §2）"""
        return tenant_id or TenantGuard.current_tenant()

    def _index_name(self, tenant_id: str) -> str:
        """生成真实索引名 {prefix}_{tenant}_vector；租户标识禁止含下划线（防拼接歧义）"""
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        if "_" in tenant_id:
            raise ValueError("tenant_id 不能包含下划线 '_'（命名空间分隔符保留）")
        return f"{self._index_prefix}_{tenant_id}_vector"

    def _index_exists(self, name: str) -> bool:
        """索引是否存在（exists 接口幂等探测）"""
        try:
            return bool(self._client.indices.exists(index=name))
        except Exception as exc:
            logger.warning("elasticsearch_index_exists_failed index=%s error=%s", name, exc)
            return False

    def _ensure_index(self, tenant_id: str) -> str:
        """确保向量索引存在（auto_create_index 关闭时跳过创建；已存在/并发创建冲突均幂等）"""
        name = self._index_name(tenant_id)
        if not self._auto_create_index:
            return name
        try:
            self._client.indices.create(
                index=name,
                mappings={
                    "properties": {
                        _VECTOR_FIELD: {"type": "dense_vector", "dims": self._dims},
                        _ID_FIELD: {"type": "keyword"},
                    }
                },
                settings={"number_of_shards": 1, "number_of_replicas": 0},
                ignore_status=[400],  # resource_already_exists_exception 幂等忽略
            )
        except Exception as exc:
            logger.warning("elasticsearch_ensure_index_failed index=%s error=%s", name, exc)
        return name
