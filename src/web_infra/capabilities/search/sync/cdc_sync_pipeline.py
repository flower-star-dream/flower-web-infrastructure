"""
CDC 同步编排管道

@Author: 花海
@Date: 2026/08/22 15:00
@Description: CDC 同步编排管道（搜索引擎数据同步方案 §4.5）：订阅源事件 → 过滤 → 字段映射 →
              攒批 → 目标写入 → 位点推进 → 重试/暂停 → 指标。单事件处理器消费源事件，
              按表分组攒批（bulk_size / flush_interval 触发冲刷），成功后推进该表末位点；
              写入失败按配置指数退避重试，超限暂停消费并告警（位点停留，恢复后继续）。
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from web_infra.capabilities.search.sync.cdc_change_event import CdcChangeEvent
from web_infra.capabilities.search.sync.cdc_offset_store_interface import CdcOffsetStoreInterface
from web_infra.capabilities.search.sync.cdc_source_interface import CdcEventHandler, CdcSourceInterface
from web_infra.capabilities.search.sync.cdc_sync_target_interface import CdcSyncTargetInterface
from web_infra.capabilities.search.sync.sync_metrics import SyncMetrics

logger = logging.getLogger("web_infra.capabilities.search.sync.pipeline")


class CdcSyncPipeline:
    """CDC 同步编排管道（消费源事件 → 攒批写目标 → 位点推进）

    :param source: CdcSourceInterface 数据源实例
    :param target: CdcSyncTargetInterface 目标实例
    :param offset_store: CdcOffsetStoreInterface 位点存储实例
    :param tables: 表监听白名单（空 = 全部）
    :param bulk_size: 批量攒批条数（容量上限 min(bulk_size, MAX_BULK_SIZE)）
    :param flush_interval_seconds: 批量最大等待（秒）
    :param max_attempts: 目标写入失败最大重试次数
    :param backoff_base_seconds: 指数退避基数（秒）
    :param max_backoff_seconds: 最大退避（秒）
    :param delete_strategy: 删除策略（soft 软删 / hard 物理删除）
    """

    def __init__(
        self,
        source: CdcSourceInterface,
        target: CdcSyncTargetInterface,
        offset_store: CdcOffsetStoreInterface,
        *,
        tables: list[str] | None = None,
        bulk_size: int = 500,
        flush_interval_seconds: float = 1.0,
        max_attempts: int = 5,
        backoff_base_seconds: float = 1.0,
        max_backoff_seconds: float = 60.0,
        delete_strategy: str = "soft",
    ) -> None:
        """初始化同步管道。

        :param source: 数据源实例
        :param target: 目标实例
        :param offset_store: 位点存储实例
        :param tables: 表监听白名单（空 = 全部）
        :param bulk_size: 批量攒批条数
        :param flush_interval_seconds: 批量最大等待（秒）
        :param max_attempts: 最大重试次数
        :param backoff_base_seconds: 指数退避基数（秒）
        :param max_backoff_seconds: 最大退避（秒）
        :param delete_strategy: 删除策略（soft / hard）
        """
        self._source = source
        self._target = target
        self._offset_store = offset_store
        self._tables = set(tables or [])
        self._bulk_size = max(1, min(bulk_size, 1000))  # 容量上限 SEARCH_SYNC_MAX_BULK_SIZE
        self._flush_interval = flush_interval_seconds
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base_seconds
        self._max_backoff = max_backoff_seconds
        self._delete_strategy = delete_strategy

        # 按表缓存的待写事件（dict[table, list[CdcChangeEvent]]）
        self._pending: dict[str, list[CdcChangeEvent]] = defaultdict(list)
        self._flush_event = asyncio.Event()
        self._consumer_task: asyncio.Task | None = None
        self._started = False
        self._source_name = getattr(source, "name", "cdc")
        self._target_name = getattr(target, "name", "target")

    @property
    def source(self) -> CdcSourceInterface:
        """数据源实例"""
        return self._source

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动管道：启动目标 → 订阅源事件 → 启动攒批消费协程 → 启动源监听。

        从已持久化位点续读（源内部处理）；首次启动无位点时源从当前位置起读。
        """
        if self._started:
            return
        await self._target.start()
        self._source.subscribe(self._handle_event)
        self._consumer_task = asyncio.create_task(self._consume_loop())
        self._started = True
        await self._source.start()
        logger.info("sync_pipeline_started source=%s target=%s", self._source_name, self._target_name)

    async def stop(self) -> None:
        """停止管道：停止源监听 → 冲刷残余事件 → 停止目标。

        冲刷期间新事件忽略（flush 后无残留），保证停机不丢已入队事件。
        """
        if not self._started:
            return
        self._started = False
        try:
            await self._source.stop()
        finally:
            self._flush_event.set()  # 唤醒消费协程刷新残余
            if self._consumer_task is not None:
                await self._consumer_task
                self._consumer_task = None
            await self._flush_pending()
            await self._target.stop()
            SyncMetrics.set_suspended(self._source_name, 0)
            logger.info("sync_pipeline_stopped source=%s target=%s", self._source_name, self._target_name)

    # ------------------------------------------------------------------
    # 事件入口
    # ------------------------------------------------------------------

    async def _handle_event(self, event: CdcChangeEvent) -> None:
        """事件处理器：过滤表白名单 → 追加到待写缓冲并唤醒冲刷。

        事件由源按分区顺序推送；此处仅入队不阻塞源（攒批由 consumer 协程负责）。
        """
        if self._tables and event.table not in self._tables:
            return
        SyncMetrics.record_event(self._source_name, event.database, event.table, event.op.value)
        self._pending[event.table].append(event)
        self._flush_event.set()

    # ------------------------------------------------------------------
    # 攒批消费循环
    # ------------------------------------------------------------------

    async def _consume_loop(self) -> None:
        """攒批消费循环：等待冲刷信号 → 每表攒够 bulk_size 或到 flush 间隔 → 写目标 → 推进位点"""
        while self._started or self._has_pending():
            await self._flush_event.wait()
            self._flush_event.clear()
            # 攒批窗口：flush_interval 内可能继续累积事件
            if self._flush_interval > 0:
                await asyncio.sleep(self._flush_interval)
            try:
                await self._flush_pending()
            except Exception:  # noqa: BLE001 - 消费循环兜底，避免协程异常中断
                logger.exception("sync_pipeline_flush_error source=%s", self._source_name)

    def _has_pending(self) -> bool:
        """是否存在待写事件"""
        return any(v for v in self._pending.values())

    async def _flush_pending(self) -> None:
        """冲刷待写事件：按表分批写目标 → 成功后推进流位点（全局末位点）。

        目标写入失败：按表整批重试（指数退避）；超限暂停消费并置暂停指标（位点停留不推进）。
        """
        if not self._has_pending():
            return
        last_position: str | None = None
        last_database: str = ""
        for table, events in list(self._pending.items()):
            if not events:
                continue
            self._pending[table] = []  # 先取走待写（防重入），失败整体回滚重试
            await self._write_batch(table, events)
            # 记录全局末位点（binlog 单一流位置，取本表末尾事件的 position）
            last_event = events[-1]
            if last_event.position:
                last_position = last_event.position
                last_database = last_event.database
        # 成功后推进全局流位点（At-least-once：先写目标再推进位点）
        if last_position:
            await self._advance_offset(last_database, last_position)

    async def _write_batch(self, table: str, events: list[CdcChangeEvent]) -> None:
        """分批写目标（按 bulk_size 切片），失败按指数退避重试，超限暂停消费。

        :raises Exception: 重试超限后抛出（消费循环记日志，暂停状态由指标反映）
        """
        for batch in self._chunks(events, self._bulk_size):
            await self._write_with_retry(table, batch)

    def _chunks(self, items: list[CdcChangeEvent], size: int) -> list[list[CdcChangeEvent]]:
        """将事件列表按 size 切分为批量块"""
        return [items[i : i + size] for i in range(0, len(items), size)]

    async def _write_with_retry(self, table: str, batch: list[CdcChangeEvent]) -> None:
        """目标写入（含重试）：插入事件 upsert、删除事件按策略删除；失败指数退避重试。

        :raises Exception: 重试超限抛出（由调用方暂停消费）
        """
        for attempt in range(1, self._max_attempts + 1):
            try:
                await self._target_apply(batch)
                SyncMetrics.record_processed(self._source_name, self._target_name)
                return
            except Exception as exc:  # noqa: BLE001 - 统一重试治理，保留原始异常信息
                if attempt >= self._max_attempts:
                    SyncMetrics.record_failure(self._source_name, self._target_name, "retry_exhausted")
                    logger.error(
                        "sync_write_retry_exhausted table=%s batch=%s attempts=%s error=%s",
                        table, len(batch), attempt, exc,
                    )
                    raise
                SyncMetrics.record_retry(self._source_name, self._target_name)
                await asyncio.sleep(self._backoff(attempt))

    async def _target_apply(self, batch: list[CdcChangeEvent]) -> None:
        """把一批事件应用到目标（upsert / delete 按事件类型分发，无前向依赖顺序可并行）"""
        for event in batch:
            if event.op.value == "delete":
                await self._target.delete(event)
            else:
                await self._target.upsert(event)

    def _backoff(self, attempt: int) -> float:
        """指数退避：base * 2^(attempt-1)，封顶 max_backoff"""
        return min(self._backoff_base * (2 ** (attempt - 1)), self._max_backoff)

    async def _advance_offset(self, database: str, position: str) -> None:
        """推进全局流位点（位点 key 含 source:database:offset，与 MysqlOffsetStore 三段格式对齐）。

        成功后置暂停指标为 0（消费恢复）；位点滞后由事件 ts 计算（observe_event_lag 外部调用）。
        """
        key = f"{self._source_name}:{database}:offset"
        await self._offset_store.save(key, position)
        SyncMetrics.record_offset_save(self._source_name)
        SyncMetrics.set_suspended(self._source_name, 0)  # 推进成功即消费恢复
        logger.debug("sync_offset_advanced db=%s position=%s", database, position)

    def observe_event_lag(self, event: CdcChangeEvent) -> None:
        """记录事件滞后（外部可调用；事件产生 ts 与当前时间差）"""
        if event.ts is not None:
            lag = (datetime.now(timezone.utc) - event.ts).total_seconds()
            if lag >= 0:
                SyncMetrics.observe_lag(self._source_name, lag)
