"""
ES 同步目标实现

@Author: 花海
@Date: 2026/08/22 15:00
@Description: ES 同步目标默认实现（搜索引擎数据同步方案 §5.5）：包装 SearchEngineInterface，
              把统一变更事件转为 ES 批量写入/删除动作。doc_id=主键拼接（稳定幂等），
              删除按 delete_strategy 软删（deleted 标记，业务检索统一过滤）或物理删除。
"""
from __future__ import annotations

import logging
from typing import Any

from web_infra.capabilities.search.search_engine_interface import SearchEngineInterface
from web_infra.capabilities.search.sync.cdc_change_event import CdcChangeEvent, CdcOp
from web_infra.capabilities.search.sync.cdc_sync_target_interface import CdcSyncTargetInterface

logger = logging.getLogger("web_infra.capabilities.search.sync.es_target")

#: 软删标记字段名（SEARCH_SYNC_DELETE_FLAG）
_DELETE_FLAG = "deleted"


class EsCdcSyncTarget(CdcSyncTargetInterface):
    """ES 同步目标（包装 SearchEngineInterface，默认实现）

    :param engine: SearchEngineInterface 实例（Elasticsearch 或内存实现）
    :param mapping: 表 → 目标索引映射（键表名，值 dict：index/fields/exclude/tenant_column/delete_strategy）
    :param host: SearchEngineInterface 的直接关联（无状态，占位兼容）
    """

    def __init__(self, engine: SearchEngineInterface, mapping: dict[str, Any] | None = None) -> None:
        """初始化 ES 同步目标。

        :param engine: SearchEngineInterface 实例
        :param mapping: 表 → 索引配置映射（缺省表名即索引名、字段全量）
        """
        self._engine = engine
        self._mapping = mapping or {}
        self._name = "es"

    @property
    def name(self) -> str:
        """目标标识（供错误码/指标区分）"""
        return self._name

    async def upsert(self, event: CdcChangeEvent) -> None:
        """写入/覆盖目标文档（INSERT/UPDATE，doc_id 幂等）"""
        if event.after is None:
            logger.warning(
                "es_sync_upsert_no_after source=%s table=%s pk=%s", event.source, event.table, event.primary_key
            )
            return
        config = self._table_config(event.table)
        tenant_id = self._extract_tenant(event.after, config)
        document = self._project_fields(event.after, config)
        await self._engine.index_document(tenant_id, config["index"], event.document_id, document)

    async def delete(self, event: CdcChangeEvent) -> None:
        """按主键删除目标文档（DELETE；软删写 deleted 标记，物理删走 delete_document）"""
        config = self._table_config(event.table)
        tenant_id = self._extract_tenant(event.after or {}, config)
        if config["delete_strategy"] == "hard":
            await self._engine.delete_document(tenant_id, config["index"], event.document_id)
            return
        # 软删：写入 deleted 标记（业务检索统一过滤 deleted=true）；保留主键字段供对账
        document: dict[str, Any] = {_DELETE_FLAG: True}
        for k, v in (event.after or {}).items():
            if k in config["fields"] or not config["fields"]:
                document[k] = v
        await self._engine.index_document(tenant_id, config["index"], event.document_id, document)

    async def start(self) -> None:
        """启动目标（占位：无需预连接；需预建索引由业务 create_index 声明）"""
        return None

    async def stop(self) -> None:
        """停止目标（占位：连接生命周期由 engine 管理）"""
        return None

    # ------------------------------------------------------------------
    # 内部：表映射 / 字段投影 / 租户提取
    # ------------------------------------------------------------------

    def _table_config(self, table: str) -> dict[str, Any]:
        """按表名解析目标配置（缺失回落默认：表名即索引、字段全量、软删）"""
        cfg = self._mapping.get(table, {})
        return {
            "index": cfg.get("index", table),
            "fields": cfg.get("fields") or [],
            "exclude": cfg.get("exclude") or [],
            "tenant_column": cfg.get("tenant_column", "tenant_id"),
            "delete_strategy": cfg.get("delete_strategy", "soft"),
        }

    def _project_fields(self, row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """字段投影：白名单（fields 非空时）→ 排除敏感字段（exclude 优先级更高）"""
        fields = config["fields"]
        exclude = set(config["exclude"])
        projected: dict[str, Any] = {}
        for k, v in row.items():
            if fields and k not in fields:
                continue
            if k in exclude:
                continue
            projected[k] = v
        return projected

    def _extract_tenant(self, row: dict[str, Any], config: dict[str, Any]) -> str | None:
        """提取租户：行含租户列则返回，否则 None（回落 no-tenant 占位，语义与 SearchEngineInterface 一致）"""
        tenant_column = config["tenant_column"]
        if not tenant_column:
            return None
        value = row.get(tenant_column)
        return str(value) if value not in (None, "") else None
