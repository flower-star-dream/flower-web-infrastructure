"""
搜索引擎同步指标采集器

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 搜索引擎同步链路指标（搜索引擎数据同步方案 §10.1）：事件/成功/失败/重试/滞后/
              位点读写/暂停/对账差异与耗时。懒注册模式：指标仅在同步调用时注册，
              标签为低基数（source/database/table/op/mode），不携带高基数动态值（规范 §18）。
"""
from __future__ import annotations

from threading import Lock
from typing import ClassVar

from prometheus_client import Counter, Gauge, REGISTRY


class SyncMetrics:
    """搜索引擎同步指标采集器（懒注册：首次记录时注册指标）"""

    _registered: ClassVar[bool] = False
    # S16-2 豁免：临界区为纯内存操作，无 I/O 阻塞，不适用 3s 获取超时
    _lock: ClassVar[Lock] = Lock()

    event_total: ClassVar[Counter | None] = None
    processed_total: ClassVar[Counter | None] = None
    failure_total: ClassVar[Counter | None] = None
    retry_total: ClassVar[Counter | None] = None
    lag_seconds: ClassVar[Gauge | None] = None
    offset_save_total: ClassVar[Counter | None] = None
    offset_load_total: ClassVar[Counter | None] = None
    suspended: ClassVar[Gauge | None] = None
    reconcile_total: ClassVar[Counter | None] = None
    reconcile_diff_total: ClassVar[Counter | None] = None
    reconcile_duration_seconds: ClassVar[Gauge | None] = None

    @classmethod
    def ensure(cls) -> None:
        """注册同步指标（线程安全，仅首次执行）"""
        if cls._registered:
            return
        with cls._lock:
            if cls._registered:
                return
            cls.event_total = Counter(
                "search_sync_event_total", "同步变更事件数", ["source", "database", "table", "op"]
            )
            cls.processed_total = Counter(
                "search_sync_processed_total", "同步成功事件数", ["source", "target"]
            )
            cls.failure_total = Counter(
                "search_sync_failure_total", "同步失败事件数", ["source", "target", "reason"]
            )
            cls.retry_total = Counter("search_sync_retry_total", "同步写入重试次数", ["source", "target"])
            cls.lag_seconds = Gauge("search_sync_lag_seconds", "位点滞后（秒）", ["source"])
            cls.offset_save_total = Counter("search_sync_offset_save_total", "位点写入次数", ["source"])
            cls.offset_load_total = Counter("search_sync_offset_load_total", "位点读取次数", ["source"])
            cls.suspended = Gauge("search_sync_suspended", "暂停状态（1=暂停消费）", ["source"])
            cls.reconcile_total = Counter("search_sync_reconcile_total", "对账执行次数", ["mode"])
            cls.reconcile_diff_total = Counter(
                "search_sync_reconcile_diff_total", "对账差异数", ["table", "action"]
            )
            cls.reconcile_duration_seconds = Gauge("search_sync_reconcile_duration_seconds", "对账耗时（秒）", ["mode"])
            cls._registered = True

    @classmethod
    def unregister_metrics(cls) -> None:
        """卸载同步指标（组件关闭时调用，规范 §16.5 扩展点注册与生命周期绑定）。
        指标已不存在时静默忽略。
        """
        with cls._lock:
            if not cls._registered:
                return
            for metric in (
                cls.event_total, cls.processed_total, cls.failure_total, cls.retry_total,
                cls.lag_seconds, cls.offset_save_total, cls.offset_load_total, cls.suspended,
                cls.reconcile_total, cls.reconcile_diff_total, cls.reconcile_duration_seconds,
            ):
                if metric is not None:
                    try:
                        REGISTRY.unregister(metric)  # type: ignore[arg-type]
                    except KeyError:
                        pass
            cls.event_total = None
            cls.processed_total = None
            cls.failure_total = None
            cls.retry_total = None
            cls.lag_seconds = None
            cls.offset_save_total = None
            cls.offset_load_total = None
            cls.suspended = None
            cls.reconcile_total = None
            cls.reconcile_diff_total = None
            cls.reconcile_duration_seconds = None
            cls._registered = False

    @classmethod
    def record_event(cls, source: str, database: str, table: str, op: str) -> None:
        """记录接收变更事件数"""
        cls.ensure()
        assert cls.event_total is not None
        cls.event_total.labels(source, database, table, op).inc()

    @classmethod
    def record_processed(cls, source: str, target: str) -> None:
        """记录成功同步事件数"""
        cls.ensure()
        assert cls.processed_total is not None
        cls.processed_total.labels(source, target).inc()

    @classmethod
    def record_failure(cls, source: str, target: str, reason: str) -> None:
        """记录失败事件数（reason: retry_exhausted / offset_lost / target_error）"""
        cls.ensure()
        assert cls.failure_total is not None
        cls.failure_total.labels(source, target, reason).inc()

    @classmethod
    def record_retry(cls, source: str, target: str) -> None:
        """记录目标写入重试次数"""
        cls.ensure()
        assert cls.retry_total is not None
        cls.retry_total.labels(source, target).inc()

    @classmethod
    def observe_lag(cls, source: str, lag_seconds: float) -> None:
        """记录位点滞后（事件产生到处理完成的秒数）"""
        cls.ensure()
        assert cls.lag_seconds is not None
        cls.lag_seconds.labels(source).set(lag_seconds)

    @classmethod
    def record_offset_save(cls, source: str) -> None:
        """记录位点写入次数"""
        cls.ensure()
        assert cls.offset_save_total is not None
        cls.offset_save_total.labels(source).inc()

    @classmethod
    def record_offset_load(cls, source: str) -> None:
        """记录位点读取次数"""
        cls.ensure()
        assert cls.offset_load_total is not None
        cls.offset_load_total.labels(source).inc()

    @classmethod
    def set_suspended(cls, source: str, value: int) -> None:
        """设置暂停状态（1=暂停消费，用于告警）"""
        cls.ensure()
        assert cls.suspended is not None
        cls.suspended.labels(source).set(value)

    @classmethod
    def record_reconcile(cls, mode: str) -> None:
        """记录对账执行次数"""
        cls.ensure()
        assert cls.reconcile_total is not None
        cls.reconcile_total.labels(mode).inc()

    @classmethod
    def record_reconcile_diff(cls, table: str, action: str) -> None:
        """记录对账差异数（action: missing / extra）"""
        cls.ensure()
        assert cls.reconcile_diff_total is not None
        cls.reconcile_diff_total.labels(table, action).inc()

    @classmethod
    def observe_reconcile_duration(cls, mode: str, seconds: float) -> None:
        """记录对账耗时（秒）"""
        cls.ensure()
        assert cls.reconcile_duration_seconds is not None
        cls.reconcile_duration_seconds.labels(mode).set(seconds)
