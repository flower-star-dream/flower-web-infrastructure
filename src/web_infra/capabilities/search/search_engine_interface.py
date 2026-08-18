"""
搜索引擎统一抽象接口

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 全文搜索引擎 SPI（搜索引擎接入计划 v0.2.0 §3.2）：索引生命周期管理、
              单条/批量写入、删除、关键词检索（分页/高亮）。
              业务代码只依赖本接口，ES / 内存 / 自研实现差异内部屏蔽。
              tenant_id 为可选参数（租户非系统必备，2026-08-18 评审调整）：
              显式传入时按租户隔离命名空间；缺省从请求上下文（RequestContext）读取；
              再无则回落 no-tenant 占位（多租户规范 §2，单租户系统所有数据收敛同一命名空间）。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from web_infra.capabilities.search.search_hit import SearchHit
from web_infra.capabilities.search.search_query import SearchQuery


@runtime_checkable
class SearchEngineInterface(Protocol):
    """全文搜索引擎统一抽象（索引生命周期 / 写入 / 删除 / 关键词检索）"""

    async def create_index(
        self,
        tenant_id: str | None,
        index_name: str,
        *,
        mappings: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        """创建索引（幂等：已存在时不报错）。

        :param tenant_id: 租户标识（可选：显式传则按租户隔离；缺省读请求上下文，再无回落 no-tenant 占位）
        :param index_name: 业务索引名（实现方按租户前缀隔离真实索引）
        :param mappings: 自定义 mapping（含分析器/分词器字段，如 IK 中文分词）
        :param settings: 自定义索引 settings（number_of_shards 等，缺省回落实现默认值）
        """
        ...

    async def delete_index(self, tenant_id: str | None, index_name: str) -> None:
        """删除索引（幂等：不存在时不报错）。

        :param tenant_id: 租户标识（可选，语义同 create_index）
        :param index_name: 业务索引名
        """
        ...

    async def index_document(
        self,
        tenant_id: str | None,
        index_name: str,
        doc_id: str,
        document: dict[str, Any],
        *,
        refresh: bool = False,
    ) -> None:
        """写入/覆盖单条文档（doc_id 幂等：同名覆盖，全量替换）。

        :param tenant_id: 租户标识（可选，语义同 create_index）
        :param index_name: 业务索引名
        :param doc_id: 文档唯一标识（业务侧自行生成，如雪花 ID / 业务主键）
        :param document: 文档内容（可检索字段，键值对；实现方负责分词/建倒排）
        :param refresh: 写入后是否刷新（ES 实现立即可查；默认 false 走近实时语义）
        """
        ...

    async def bulk_index(
        self,
        tenant_id: str | None,
        index_name: str,
        documents: list[dict[str, Any]],
        *,
        refresh: bool = False,
    ) -> None:
        """批量写入文档（幂等：元素含相同 id 时覆盖）。

        :param tenant_id: 租户标识（可选，语义同 create_index）
        :param index_name: 业务索引名
        :param documents: 文档列表，每项必须含 id 键（文档唯一标识，不写入内容），
            其余键值对为文档内容；缺 id 的项跳过（实现方记录告警，不中断整批）
        :param refresh: 写入后是否刷新（默认 false）
        """
        ...

    async def delete_document(
        self,
        tenant_id: str | None,
        index_name: str,
        doc_id: str,
        *,
        refresh: bool = False,
    ) -> None:
        """按文档 ID 删除（幂等：不存在时静默，不抛错）。

        :param tenant_id: 租户标识（可选，语义同 create_index）
        :param index_name: 业务索引名
        :param doc_id: 文档唯一标识
        :param refresh: 删除后是否刷新（默认 false）
        """
        ...

    async def search(self, tenant_id: str | None, query: SearchQuery) -> list[SearchHit]:
        """关键词检索，按相关性得分降序返回。

        :param tenant_id: 租户标识（可选：显式传则仅检索该租户；缺省读请求上下文，再无回落 no-tenant 占位）
        :param query: 检索参数（关键词 / 索引名 / 分页 / 高亮）
        :return: 命中文档列表（含得分、原文与可选高亮片段）；无命中返回空列表
        """
        ...
