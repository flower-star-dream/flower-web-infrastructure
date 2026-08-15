"""
向量存储接口

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 向量库抽象（SPI，AI 规范 §11），提供增删查与按 ID 取回，
              默认内存实现；FAISS 等真实向量库可通过该接口接入。
              所有读写方法均要求显式传入 tenant_id（多租户规范 §2：检索结果遵守数据权限，
              禁止跨租户命中知识库内容），实现方必须按租户隔离命名空间。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from web_infra.ai.retrieval.vector_hit import VectorHit


class VectorStoreInterface(ABC):
    """向量存储接口（租户维度隔离）"""

    @abstractmethod
    def add(self, tenant_id: str, ids: list[str], vectors: list[list[float]]) -> None:
        """批量写入向量（ID 与向量一一对应，仅写入指定租户命名空间）。

        :param tenant_id: 租户标识（必填，数据仅对该租户可见）
        :param ids: 向量 ID 列表
        :param vectors: 向量列表（与 ids 一一对应）
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, tenant_id: str, ids: list[str]) -> None:
        """批量删除指定租户下的向量。

        :param tenant_id: 租户标识（必填）
        :param ids: 待删除的向量 ID 列表
        """
        raise NotImplementedError

    @abstractmethod
    def search(self, tenant_id: str, query_vector: list[float], top_k: int) -> list[VectorHit]:
        """按相似度检索指定租户命名空间内的 top_k 个命中（得分越大越相似）。

        :param tenant_id: 租户标识（必填，仅检索该租户数据）
        :param query_vector: 查询向量
        :param top_k: 返回命中数
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, tenant_id: str, ids: list[str]) -> dict[str, list[float]]:
        """按 ID 取回指定租户下的向量（用于邻居扩展等场景），未找到的 ID 不返回。

        :param tenant_id: 租户标识（必填）
        :param ids: 向量 ID 列表
        """
        raise NotImplementedError

    @abstractmethod
    def ids_in_order(self, tenant_id: str) -> list[str]:
        """按写入顺序返回指定租户下全部向量 ID（供邻居扩展定位相邻块）。

        :param tenant_id: 租户标识（必填）
        """
        raise NotImplementedError
