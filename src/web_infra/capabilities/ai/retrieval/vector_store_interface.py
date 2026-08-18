"""
向量存储接口

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 向量库抽象（SPI，AI 规范 §11），提供增删查与按 ID 取回，
              默认内存实现；FAISS / Elasticsearch 等真实向量库可通过该接口接入。
              tenant_id 为可选参数（租户非系统必备，2026-08-18 评审调整，与
              SearchEngineInterface 一致）：显式传入时按租户隔离命名空间；缺省从请求上下文
              （RequestContext）读取；再无则回落 no-tenant 占位（多租户规范 §2，
              单租户系统所有数据收敛同一命名空间，隔离退化为全局共享）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from web_infra.capabilities.ai.retrieval.vector_hit import VectorHit


class VectorStoreInterface(ABC):
    """向量存储接口（租户维度隔离，tenant_id 可选）"""

    @abstractmethod
    def add(self, tenant_id: str | None, ids: list[str], vectors: list[list[float]]) -> None:
        """批量写入向量（ID 与向量一一对应，仅写入指定租户命名空间）。

        :param tenant_id: 租户标识（可选：显式传则隔离；缺省读请求上下文，再无回落 no-tenant 占位）
        :param ids: 向量 ID 列表
        :param vectors: 向量列表（与 ids 一一对应）
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, tenant_id: str | None, ids: list[str]) -> None:
        """批量删除指定租户下的向量。

        :param tenant_id: 租户标识（可选，语义同 add）
        :param ids: 待删除的向量 ID 列表
        """
        raise NotImplementedError

    @abstractmethod
    def search(self, tenant_id: str | None, query_vector: list[float], top_k: int) -> list[VectorHit]:
        """按相似度检索指定租户命名空间内的 top_k 个命中（得分越大越相似）。

        :param tenant_id: 租户标识（可选：显式传则仅检索该租户；缺省读请求上下文，再无回落 no-tenant 占位）
        :param query_vector: 查询向量
        :param top_k: 返回命中数
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, tenant_id: str | None, ids: list[str]) -> dict[str, list[float]]:
        """按 ID 取回指定租户下的向量（用于邻居扩展等场景），未找到的 ID 不返回。

        :param tenant_id: 租户标识（可选，语义同 add）
        :param ids: 向量 ID 列表
        """
        raise NotImplementedError

    @abstractmethod
    def ids_in_order(self, tenant_id: str | None) -> list[str]:
        """按写入顺序返回指定租户下全部向量 ID（供邻居扩展定位相邻块）。

        :param tenant_id: 租户标识（可选，语义同 add）
        """
        raise NotImplementedError
