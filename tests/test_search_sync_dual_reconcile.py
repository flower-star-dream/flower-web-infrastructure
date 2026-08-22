"""
搜索引擎同步：双写 / 对账 / 错误码 / 导出测试

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 覆盖 SearchSyncOutboxWriter（事务内写 outbox 记录）、SearchSyncOutboxConsumer
              （幂等消费写目标）、FullReconcileService（对账/重建分批）、同步错误码注册、
              同步常量与顶层导出。mock 目标与 outbox 存储，不触网。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import web_infra  # noqa: E402
from web_infra.capabilities.search.sync.cdc_change_event import CdcChangeEvent, CdcOp  # noqa: E402
from web_infra.capabilities.search.sync.dual_write_sync_service import (  # noqa: E402
    SearchSyncOutboxConsumer,
    SearchSyncOutboxWriter,
)
from web_infra.capabilities.search.sync.full_reconcile_service import FullReconcileService  # noqa: E402
from web_infra.capabilities.search.sync.search_sync_constant import SearchSyncConstant  # noqa: E402
from web_infra.capabilities.search.sync.search_sync_error_code import (  # noqa: E402
    SearchSyncErrorCode,
    SearchSyncErrorCodeEnum,
)
from web_infra.infra.error import ErrorCodeRegistry  # noqa: E402


class _FakeTarget:
    """记录调用序列的内存目标"""

    def __init__(self) -> None:
        self.upserts: list[CdcChangeEvent] = []
        self.deletes: list[CdcChangeEvent] = []

    async def upsert(self, event: CdcChangeEvent) -> None:
        self.upserts.append(event)

    async def delete(self, event: CdcChangeEvent) -> None:
        self.deletes.append(event)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class _FakeOutboxStore:
    """记录追加记录的内存 outbox 存储"""

    def __init__(self) -> None:
        self.appended: list = []

    async def append(self, record, session=None) -> None:
        self.appended.append(record)
        return record


class _FakeIdempotent:
    """内存幂等消费封装（first=True 首次执行，False 跳过）"""

    def __init__(self, first: bool = True) -> None:
        self.first = first

    async def consume(self, message, handler) -> bool:
        if not self.first:
            return False
        await handler(message)
        return True


def _build_payload(table="t_order", op="insert", pk=None, after=None):
    return {
        "source": "dual_write", "database": "shop", "table": table, "op": op,
        "primary_key": pk or {"biz_id": "1"}, "before": {}, "after": after or {"biz_id": "1", "title": "苹果"},
    }


# ---------------------------------------------------------------------------
# SearchSyncOutboxWriter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dual_write_writer_records_outbox():
    """双写写入器：同事务写 outbox 记录（含业务键/操作类型/镜像）"""
    store = _FakeOutboxStore()
    writer = SearchSyncOutboxWriter(store)
    await writer.record("session", biz_id="1", table="t_order", op="insert", after={"biz_id": "1"})
    assert len(store.appended) == 1
    rec = store.appended[0]
    assert rec.topic == SearchSyncConstant.SYNC_TOPIC
    assert rec.biz_id == "1"
    assert rec.payload["op"] == "insert"
    assert rec.payload["table"] == "t_order"
    assert rec.tag == "insert"


@pytest.mark.asyncio
async def test_dual_write_writer_invalid_op_raises():
    """双写写入器：非法 op 抛 ValueError"""
    writer = SearchSyncOutboxWriter(_FakeOutboxStore())
    with pytest.raises(ValueError):
        await writer.record("session", biz_id="1", table="t_order", op="delete-all")


class _Msg:
    def __init__(self, body):
        self.body = body
        self.message_id = "m1"


# ---------------------------------------------------------------------------
# SearchSyncOutboxConsumer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dual_write_consumer_applies_insert():
    """双写消费：幂等首次执行，INSERT 事件写目标 upsert"""
    target = _FakeTarget()
    consumer = SearchSyncOutboxConsumer(_FakeIdempotent(first=True), target)
    await consumer.handle(_Msg(_build_payload(op="insert", after={"biz_id": "1", "title": "苹果"})))
    assert len(target.upserts) == 1
    assert target.upserts[0].op == CdcOp.INSERT


@pytest.mark.asyncio
async def test_dual_write_consumer_skips_duplicate():
    """双写消费：重复消费跳过（幂等）"""
    target = _FakeTarget()
    consumer = SearchSyncOutboxConsumer(_FakeIdempotent(first=False), target)
    result = await consumer.handle(_Msg(_build_payload(op="insert")))
    assert result is False
    assert len(target.upserts) == 0


@pytest.mark.asyncio
async def test_dual_write_consumer_delete_applies_delete():
    """双写消费：DELETE 事件写目标 delete"""
    target = _FakeTarget()
    consumer = SearchSyncOutboxConsumer(_FakeIdempotent(first=True), target)
    await consumer.handle(_Msg(_build_payload(op="delete", pk={"biz_id": "1"})))
    assert len(target.deletes) == 1
    assert target.deletes[0].op == CdcOp.DELETE


@pytest.mark.asyncio
async def test_dual_write_consumer_invalid_op_raises():
    """双写消费：非法 op 抛 ValueError（触发消费重试）"""
    target = _FakeTarget()
    consumer = SearchSyncOutboxConsumer(_FakeIdempotent(first=True), target)
    with pytest.raises(ValueError):
        await consumer.handle(_Msg(_build_payload(op="drop")))


# ---------------------------------------------------------------------------
# FullReconcileService
# ---------------------------------------------------------------------------


def _fake_row_reader(rows_by_call: list[list[dict]]):
    """构造分页行读取器（依次返回分批结果，末批小于 batch_size 停止）"""
    call = 0

    async def reader(table, batch_size, offset):
        nonlocal call
        if call >= len(rows_by_call):
            return []
        result = rows_by_call[call]
        call += 1
        return result

    return reader


@pytest.mark.asyncio
async def test_reconcile_scans_and_upserts():
    """对账：分批扫描全部行并 upsert（库为权威补齐方向）"""
    target = _FakeTarget()
    reader = _fake_row_reader([[{"id": "1"}, {"id": "2"}], [{"id": "3"}]])
    service = FullReconcileService(target, reader, required_id_column="id", batch_size=2)
    result = await service.reconcile("t_order")
    assert result["scanned"] == 3
    assert result["upserted"] == 3
    assert len(target.upserts) == 3
    assert target.upserts[0].table == "t_order"


@pytest.mark.asyncio
async def test_rebuild_batches_all_rows():
    """重建：分批全量写入，返回统计"""
    target = _FakeTarget()
    reader = _fake_row_reader([[{"id": "1"}], [{"id": "2"}, {"id": "3"}]])
    service = FullReconcileService(target, reader, required_id_column="id", batch_size=1, mode="rebuild")
    result = await service.run("t_order")
    assert result["scanned"] == 3
    assert result["upserted"] == 3
    assert len(target.upserts) == 3


@pytest.mark.asyncio
async def test_reconcile_missing_id_raises():
    """对账：行缺主键列抛 ValueError"""
    target = _FakeTarget()
    reader = _fake_row_reader([[{"no_id": "1"}]])
    service = FullReconcileService(target, reader, required_id_column="id")
    with pytest.raises(ValueError):
        await service.reconcile("t_order")


# ---------------------------------------------------------------------------
# 错误码 / 常量 / 导出
# ---------------------------------------------------------------------------


def test_sync_error_codes_registered():
    """同步错误码登记到注册表"""
    assert ErrorCodeRegistry.get("E3-SRCH-010").code == "E3-SRCH-010"
    assert ErrorCodeRegistry.get("E3-SRCH-011").code == "E3-SRCH-011"
    assert ErrorCodeRegistry.get("E4-SRCH-012").code == "E4-SRCH-012"
    assert ErrorCodeRegistry.get("E4-SRCH-013").code == "E4-SRCH-013"
    # 可重试标记
    assert ErrorCodeRegistry.get("E3-SRCH-010").retryable is True
    assert ErrorCodeRegistry.get("E4-SRCH-012").retryable is False
    # 枚举反查
    assert SearchSyncErrorCodeEnum.of("E3-SRCH-010") is SearchSyncErrorCodeEnum.CDC_READ_ERROR
    assert SearchSyncErrorCode.CDC_READ_ERROR.code == "E3-SRCH-010"


def test_sync_constants():
    """同步常量定义"""
    assert SearchSyncConstant.ERROR_DOMAIN == "SRCH"
    assert SearchSyncConstant.SYNC_TOPIC == "web-search-sync-topic"
    assert SearchSyncConstant.OUTBOX_EVENT_TYPE == "search-sync"
    assert SearchSyncConstant.DELETE_FLAG == "deleted"
    assert SearchSyncConstant.MAX_BULK_SIZE == 1000


def test_sync_exports_at_top_level():
    """同步符号在 web_infra 顶层导出"""
    assert hasattr(web_infra, "CdcChangeEvent")
    assert hasattr(web_infra, "CdcSyncPipeline")
    assert hasattr(web_infra, "EsCdcSyncTarget")
    assert hasattr(web_infra, "MysqlBinlogCdcSource")
    assert hasattr(web_infra, "FullReconcileService")
    assert hasattr(web_infra, "SearchSyncConstant")
