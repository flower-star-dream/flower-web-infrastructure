"""
内存向量存储

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 基于内存字典的向量存储（默认实现，测试/小规模场景），
              线性扫描余弦相似度检索；真实大规模场景建议接入 FAISS / ES 等实现 VectorStoreInterface。
              tenant_id 可选（2026-08-18 评审调整，与 SearchEngineInterface 一致）：显式传则按租户隔离；
              缺省读请求上下文（TenantGuard.current_tenant），再无回落 no-tenant 占位——
              单租户系统无需传租户，所有数据收敛同一命名空间，隔离退化为全局共享。
              内部按（解析后租户）划分命名空间（多租户规范 §2：禁止跨租户命中知识库内容）。
"""
from __future__ import annotations

import math
from threading import Lock

from web_infra.capabilities.ai.retrieval.vector_hit import VectorHit
from web_infra.capabilities.ai.retrieval.vector_store_interface import VectorStoreInterface
from web_infra.capabilities.db.tenant_guard import TenantGuard


class InMemoryVectorStore(VectorStoreInterface):
    """内存向量存储（默认实现，租户维度隔离）

    @Stateful：进程内内存存储，单实例/单进程部署，多实例需替换为分布式实现（S1-1）。
    """

    def __init__(self, max_vectors_per_tenant: int | None = None) -> None:
        """初始化内存向量存储。

        :param max_vectors_per_tenant: 单租户向量条数上限（None 表示不限制，默认兼容旧行为；
            生产建议配置上限并定期重建，防止向量无限累积导致内存增长）
        """
        # 租户命名空间：{tenant_id: {vector_id: vector}}，每个租户独立存储
        self._store: dict[str, dict[str, list[float]]] = {}
        # 租户写入顺序：{tenant_id: [vector_id, ...]}，供邻居扩展定位相邻块
        self._order: dict[str, list[str]] = {}
        self._max_vectors_per_tenant = max_vectors_per_tenant
        self._lock = Lock()

    @staticmethod
    def _resolve_tenant(tenant_id: str | None) -> str:
        """解析租户标识：显式传入优先；否则从请求上下文读取；再无则 no-tenant 占位（多租户规范 §2）"""
        return tenant_id or TenantGuard.current_tenant()

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """余弦相似度"""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    def add(self, tenant_id: str | None, ids: list[str], vectors: list[list[float]]) -> None:
        """批量写入向量（仅写入指定租户命名空间；超出容量上限时淘汰最旧写入的向量）"""
        if len(ids) != len(vectors):
            raise ValueError("ids 与 vectors 长度不一致")
        tenant_id = self._resolve_tenant(tenant_id)
        with self._lock:
            data = self._store.setdefault(tenant_id, {})
            order = self._order.setdefault(tenant_id, [])
            for vid, vector in zip(ids, vectors):
                if vid not in data:
                    order.append(vid)
                data[vid] = vector
            # 容量上限：超限后按写入顺序淘汰最旧向量（防内存无限增长）
            if self._max_vectors_per_tenant is not None and len(data) > self._max_vectors_per_tenant:
                overflow = len(data) - self._max_vectors_per_tenant
                for old_vid in order[:overflow]:
                    data.pop(old_vid, None)
                del order[:overflow]

    def delete(self, tenant_id: str | None, ids: list[str]) -> None:
        """批量删除指定租户下的向量"""
        tenant_id = self._resolve_tenant(tenant_id)
        with self._lock:
            data = self._store.get(tenant_id)
            if not data:
                return
            for vid in ids:
                data.pop(vid, None)
            self._order[tenant_id] = [vid for vid in self._order[tenant_id] if vid in data]

    def search(self, tenant_id: str | None, query_vector: list[float], top_k: int) -> list[VectorHit]:
        """按相似度检索指定租户命名空间内的 top_k 个命中"""
        tenant_id = self._resolve_tenant(tenant_id)
        with self._lock:
            data = self._store.get(tenant_id, {})
            scored = [
                (vid, self._cosine_similarity(query_vector, vector), vector)
                for vid, vector in data.items()
            ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return [VectorHit(id=vid, score=score, vector=vector) for vid, score, vector in scored[:top_k]]

    def get(self, tenant_id: str | None, ids: list[str]) -> dict[str, list[float]]:
        """按 ID 取回指定租户下的向量，未找到的 ID 不返回"""
        tenant_id = self._resolve_tenant(tenant_id)
        with self._lock:
            data = self._store.get(tenant_id, {})
            return {vid: data[vid] for vid in ids if vid in data}

    def ids_in_order(self, tenant_id: str | None) -> list[str]:
        """按写入顺序返回指定租户下全部向量 ID"""
        tenant_id = self._resolve_tenant(tenant_id)
        with self._lock:
            return list(self._order.get(tenant_id, []))
