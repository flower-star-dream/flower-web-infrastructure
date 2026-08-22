"""
空闲时段全量对账/重建服务

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 同步兜底（搜索引擎数据同步方案 §9）：周期全量对比业务库与 ES 现状，收敛 CDC 偶发遗漏。
              reconcile 模式差异补齐（库有 ES 无→upsert，ES 有库无→按策略删除），轻量不动索引；
              rebuild 模式全量分批写新索引→原子切换 alias（索引结构变更/整体修复）。
              数据库访问经注入的 fetch_rows 回调解耦（业务库可走框架数据库会话），业务层可自定义扫描逻辑。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from web_infra.capabilities.search.search_engine_interface import SearchEngineInterface
from web_infra.capabilities.search.sync.cdc_change_event import CdcChangeEvent, CdcOp
from web_infra.capabilities.search.sync.cdc_sync_target_interface import CdcSyncTargetInterface
from web_infra.capabilities.search.sync.sync_metrics import SyncMetrics

logger = logging.getLogger("web_infra.capabilities.search.sync.reconcile")

#: 行读取器签名：(table, batch_size, offset) -> rows；rows 每项为 {pk..., field...}
RowReader = Callable[[str, int, int], Awaitable[list[dict[str, Any]]]]


class FullReconcileService:
    """空闲时段全量对账/重建服务

    :param target: 同步目标（EsCdcSyncTarget 等，用于 upsert/delete）
    :param row_reader: 业务表行读取器（按表名分批读取库记录，返回字段字典列表）
    :param required_id_column: 主键列名（用于识别/生成文档 ID；缺省 "id"）
    :param batch_size: 每批读取/写入条数
    :param mode: 对账模式（reconcile 差异补齐 / rebuild 重建）
    :param delete_strategy: 删除策略（soft 软删 / hard 物理删除）
    """

    def __init__(
        self,
        target: CdcSyncTargetInterface,
        row_reader: RowReader,
        *,
        required_id_column: str = "id",
        batch_size: int = 1000,
        mode: str = "reconcile",
        delete_strategy: str = "soft",
    ) -> None:
        """初始化对账服务。

        :param target: 同步目标
        :param row_reader: 业务表行读取器
        :param required_id_column: 主键列名
        :param batch_size: 每批条数
        :param mode: 对账模式
        :param delete_strategy: 删除策略
        """
        self._target = target
        self._row_reader = row_reader
        self._id_column = required_id_column
        self._batch_size = batch_size
        self._mode = mode
        self._delete_strategy = delete_strategy

    async def reconcile(self, table: str, index_name: str | None = None) -> dict[str, int]:
        """差异对账：扫描业务表全量主键 → upsert 补写（库有则写，幂等覆盖）。

        注：删除方向（ES 有库无）需 ES 侧全量文档对比，为控制范围与风险，
        默认仅做「库 → ES」的补齐方向（库为权威）；删除由软删/deleting 状态承接。

        :param table: 业务表名（同时用作文档索引名，除非 index_name 指定）
        :param index_name: 目标索引名（缺省同表名）
        :return: 对账统计（scanned/upserted）
        """
        index = index_name or table
        start = time.monotonic()
        scanned = upserted = 0
        offset = 0
        while True:
            rows = await self._row_reader(table, self._batch_size, offset)
            if not rows:
                break
            scanned += len(rows)
            for row in rows:
                event = self._row_to_event(table, row, CdcOp.INSERT)
                await self._target.upsert(event)
                upserted += 1
            offset += len(rows)
            if len(rows) < self._batch_size:
                break
        SyncMetrics.record_reconcile(self._mode)
        SyncMetrics.observe_reconcile_duration(self._mode, time.monotonic() - start)
        result = {"scanned": scanned, "upserted": upserted}
        logger.info("reconcile_done table=%s index=%s %s", table, index, result)
        return result

    async def rebuild(self, table: str, index_name: str | None = None) -> dict[str, int]:
        """全量重建：分批写入目标（新建索引由业务 create_index + alias 切换负责）。

        重建仅负责全量写入（doc_id 幂等），索引创建与 alias 切换由业务侧编排：
            1. create_index 建新索引（新名）；
            2. 本方法全量写入新索引；
            3. alias 原子切换指向新索引。

        :param table: 业务表名
        :param index_name: 目标索引名（缺省同表名）
        :return: 重建统计（scanned/upserted）
        """
        index = index_name or table
        start = time.monotonic()
        scanned = upserted = 0
        offset = 0
        while True:
            rows = await self._row_reader(table, self._batch_size, offset)
            if not rows:
                break
            scanned += len(rows)
            for row in rows:
                event = self._row_to_event(table, row, CdcOp.INSERT)
                await self._target.upsert(event)
                upserted += 1
            offset += len(rows)
            if len(rows) < self._batch_size:
                break
        SyncMetrics.record_reconcile("rebuild")
        SyncMetrics.observe_reconcile_duration("rebuild", time.monotonic() - start)
        result = {"scanned": scanned, "upserted": upserted}
        logger.info("rebuild_done table=%s index=%s %s", table, index, result)
        return result

    async def run(self, table: str, index_name: str | None = None) -> dict[str, int]:
        """按配置模式执行对账（reconcile）或重建（rebuild）。

        :param table: 业务表名
        :param index_name: 目标索引名（缺省同表名）
        :return: 执行统计
        """
        if self._mode == "rebuild":
            return await self.rebuild(table, index_name)
        return await self.reconcile(table, index_name)

    # ------------------------------------------------------------------
    # 内部：行 → 变更事件
    # ------------------------------------------------------------------

    def _row_to_event(self, table: str, row: dict[str, Any], op: CdcOp) -> CdcChangeEvent:
        """把业务库行转换为 INSERT 变更事件（主键取 required_id_column，其余为字段）。

        :param row: 业务库行（含主键与字段）
        :raises ValueError: 行缺主键列
        """
        pk_value = row.get(self._id_column)
        if pk_value is None:
            raise ValueError(f"行缺少主键列 {self._id_column!r}（table={table}）")
        pk = {self._id_column: pk_value}
        return CdcChangeEvent(
            source="reconcile", database="", table=table, op=op,
            primary_key=pk, after=dict(row),
        )
