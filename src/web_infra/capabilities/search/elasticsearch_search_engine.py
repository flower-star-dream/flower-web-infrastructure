"""
Elasticsearch 搜索引擎（生产实现）

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 基于官方 elasticsearch-dsl（ORM 风格）的全文搜索引擎生产实现
              （搜索引擎接入计划 v0.2.0 §3.2）：AsyncSearch 检索 DSL、AsyncIndex 索引管理、
              client 写入（index/bulk/delete）。真实索引名按
              {index_prefix}_{tenant_id}_{index_name} 隔离（多租户规范 §2：禁止跨租户命中）。
              tenant_id 可选（2026-08-18 评审调整）：显式传则按租户隔离；缺省读请求上下文
              （TenantGuard.current_tenant），再无回落 no-tenant 占位（单租户收敛同一命名空间）。
              create_index 支持业务自定义 mapping/settings（含 IK 等中文分词分析器配置入口）。
              依赖 es extra（elasticsearch-dsl>=8.0，自动携带 elasticsearch-py）：
              延迟导入，未安装 es extra 时导入本模块不报错，构造实例才加载并给出安装提示。
"""
from __future__ import annotations

import logging
from typing import Any

from web_infra.capabilities.db.tenant_guard import TenantGuard
from web_infra.capabilities.search.search_engine_interface import SearchEngineInterface
from web_infra.capabilities.search.search_error_code import SearchErrorCode
from web_infra.capabilities.search.search_hit import SearchHit
from web_infra.capabilities.search.search_query import SearchQuery

logger = logging.getLogger("web_infra.capabilities.search.elasticsearch")

# 默认索引 settings（分片/副本，业务可经 create_index settings 覆盖）
_DEFAULT_INDEX_SETTINGS = {"number_of_shards": 1, "number_of_replicas": 0}


class ElasticsearchSearchEngine:
    """Elasticsearch 全文搜索引擎（SearchEngineInterface 生产实现，租户前缀隔离索引）"""

    def __init__(
        self,
        *,
        hosts: list[str] | str | None = None,
        index_prefix: str = "web",
        username: str = "",
        password: str = "",
        verify_certs: bool = True,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
        client: Any | None = None,
    ) -> None:
        """初始化 ES 搜索引擎。

        :param hosts: ES 节点地址（列表或逗号分隔字符串；注入 client 时可不传）
        :param index_prefix: 真实索引名前缀（{prefix}_{tenant}_{index}）
        :param username/password: 账号密码（空表示无需认证）
        :param verify_certs: TLS 证书校验（生产默认开启）
        :param connect_timeout/read_timeout: 连接/读超时（秒）
        :param client: 注入 AsyncElasticsearch 实例（测试用；缺省按 hosts 自动创建）
        :raises ImportError: 未安装 es extra（elasticsearch-dsl）
        :raises ValueError: 未注入 client 且 hosts 为空
        """
        self._index_prefix = index_prefix
        if client is not None:
            self._client = client
            return
        if not hosts:
            raise ValueError("hosts 不能为空（未注入 client 时需提供 ES 节点地址）")
        try:
            from elasticsearch import AsyncElasticsearch
        except ImportError as exc:  # 延迟导入：未安装 es extra 时给出明确安装指引
            raise ImportError(
                "ElasticsearchSearchEngine 需要安装 es extra：pip install 'flower-web-infrastructure[es]'"
            ) from exc
        kwargs: dict[str, Any] = {"verify_certs": verify_certs, "request_timeout": read_timeout}
        if username:
            kwargs["basic_auth"] = (username, password)
        self._client = AsyncElasticsearch(hosts=hosts, **kwargs)

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
        """创建索引（幂等：已存在时静默；mappings 支持业务自定义分析器/分词器）。

        索引创建走底层 indices.create（body 完全自定义，mappings/settings 原样透传，
        含 IK 等中文分词 analysis 配置入口）；检索与写入走 elasticsearch-dsl ORM。
        """
        from elasticsearch import BadRequestError

        tenant_id = self._resolve_tenant(tenant_id)
        name = self._index_name(tenant_id, index_name)
        body: dict[str, Any] = {"settings": {**_DEFAULT_INDEX_SETTINGS, **(settings or {})}}
        if mappings:
            body["mappings"] = mappings
        try:
            await self._client.indices.create(index=name, body=body)
        except BadRequestError as exc:
            # resource_already_exists_exception：幂等忽略；其余错误转 E3-SRCH-001
            if "resource_already_exists_exception" not in str(exc):
                raise SearchErrorCode.SEARCH_INDEX_ERROR.to_exception(message=f"创建索引失败：{exc}") from exc
        except Exception as exc:
            raise SearchErrorCode.SEARCH_INDEX_ERROR.to_exception(message=f"创建索引失败：{exc}") from exc

    async def delete_index(self, tenant_id: str | None, index_name: str) -> None:
        """删除索引（幂等：不存在时静默）"""
        from elasticsearch import NotFoundError

        tenant_id = self._resolve_tenant(tenant_id)
        name = self._index_name(tenant_id, index_name)
        try:
            await self._client.indices.delete(index=name, ignore_status=[404])
        except NotFoundError:
            pass
        except Exception as exc:
            raise SearchErrorCode.SEARCH_INDEX_ERROR.to_exception(message=f"删除索引失败：{exc}") from exc

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
        """写入/覆盖单条文档（doc_id 幂等：同名覆盖；动态 mapping，业务字段全量透传）"""
        tenant_id = self._resolve_tenant(tenant_id)
        name = self._index_name(tenant_id, index_name)
        try:
            await self._client.index(index=name, id=doc_id, document=document, refresh=refresh)
        except Exception as exc:
            raise SearchErrorCode.SEARCH_ENGINE_ERROR.to_exception(message=f"写入文档失败：{exc}") from exc

    async def bulk_index(
        self,
        tenant_id: str | None,
        index_name: str,
        documents: list[dict[str, Any]],
        *,
        refresh: bool = False,
    ) -> None:
        """批量写入文档（元素必须含 id 键作为文档标识，不写入内容；缺 id 跳过并告警）"""
        tenant_id = self._resolve_tenant(tenant_id)
        name = self._index_name(tenant_id, index_name)
        operations: list[dict[str, Any]] = []
        for item in documents:
            doc_id = item.get("id")
            if not doc_id:
                logger.warning("bulk_index skipped_missing_id index=%s", index_name)
                continue
            operations.append({"index": {"_index": name, "_id": str(doc_id)}})
            operations.append({k: v for k, v in item.items() if k != "id"})
        if not operations:
            return
        try:
            await self._client.bulk(operations=operations, refresh=refresh)
        except Exception as exc:
            raise SearchErrorCode.SEARCH_ENGINE_ERROR.to_exception(message=f"批量写入文档失败：{exc}") from exc

    async def delete_document(
        self,
        tenant_id: str | None,
        index_name: str,
        doc_id: str,
        *,
        refresh: bool = False,
    ) -> None:
        """按文档 ID 删除（幂等：不存在时静默）"""
        from elasticsearch import NotFoundError

        tenant_id = self._resolve_tenant(tenant_id)
        name = self._index_name(tenant_id, index_name)
        try:
            await self._client.delete(index=name, id=doc_id, refresh=refresh)
        except NotFoundError:
            pass
        except Exception as exc:
            raise SearchErrorCode.SEARCH_ENGINE_ERROR.to_exception(message=f"删除文档失败：{exc}") from exc

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    async def search(self, tenant_id: str | None, query: SearchQuery) -> list[SearchHit]:
        """关键词检索：multi_match 全字段匹配 → 相关性降序 → 分页 → 可选高亮"""
        from elasticsearch import NotFoundError
        from elasticsearch_dsl import AsyncSearch, Q

        tenant_id = self._resolve_tenant(tenant_id)
        name = self._index_name(tenant_id, query.index_name)
        try:
            s = AsyncSearch(using=self._client, index=name)
            s = s.query(Q("multi_match", query=query.keyword, fields=["*"]))
            # 分页（elasticsearch-dsl 切片语法映射 ES from/size）
            s = s[query.offset : query.offset + query.size]
            if query.highlight:
                s = s.highlight(
                    "*",
                    require_field_match=False,
                    pre_tags=["<em>"],
                    post_tags=["</em>"],
                )
            response = await s.execute()
        except NotFoundError:
            # 索引不存在：检索降级返回空列表（不阻断主流程，参照 Retriever 异常降级）
            logger.warning("search index_not_found index=%s", name)
            return []
        except Exception as exc:
            raise SearchErrorCode.SEARCH_ENGINE_ERROR.to_exception(message=f"检索失败：{exc}") from exc
        hits: list[SearchHit] = []
        for hit in response.hits:
            highlight_map = getattr(hit.meta, "highlight", None)
            highlight: dict[str, list[str]] = dict(highlight_map.to_dict()) if highlight_map is not None else {}
            hits.append(
                SearchHit(
                    id=hit.meta.id,
                    score=hit.meta.score if hit.meta.score is not None else 0.0,
                    source=hit.to_dict(),
                    highlight=highlight,
                )
            )
        return hits

    # ------------------------------------------------------------------
    # 连接生命周期
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """关闭底层 ES 客户端连接（应用停机/测试收尾调用）"""
        try:
            await self._client.close()
        except Exception as exc:
            logger.warning("elasticsearch_close_failed error=%s", exc)

    # ------------------------------------------------------------------
    # 内部：租户解析 / 索引命名与隔离
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_tenant(tenant_id: str | None) -> str:
        """解析租户标识：显式传入优先；否则从请求上下文读取；再无则 no-tenant 占位（多租户规范 §2）"""
        return tenant_id or TenantGuard.current_tenant()

    def _index_name(self, tenant_id: str, index_name: str) -> str:
        """生成真实索引名 {prefix}_{tenant}_{index}；命名空间参数禁止含下划线（防拼接歧义）"""
        if not tenant_id or not index_name:
            raise ValueError("tenant_id 与 index_name 均不能为空")
        if "_" in tenant_id or "_" in index_name:
            raise ValueError("tenant_id 与 index_name 不能包含下划线 '_'（命名空间分隔符保留）")
        return f"{self._index_prefix}_{tenant_id}_{index_name}"
