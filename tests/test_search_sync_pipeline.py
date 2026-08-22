"""
搜索引擎同步：ES 目标 / 编排管道 / 配置 / 注册表测试

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 覆盖 EsCdcSyncTarget（字段投影/租户提取/软删/硬删）、CdcSyncPipeline
              （攒批/幂等/位点推进/表白名单/重试）、CdcSyncConfig（配置校验）、
              CdcSyncRegistry（注册/覆盖/未注册）。mock 目标与内存搜索引擎，不触网。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from web_infra.capabilities.search.sync.cdc_change_event import CdcChangeEvent, CdcOp  # noqa: E402
from web_infra.capabilities.search.sync.cdc_sync_config import CdcSyncConfig  # noqa: E402
from web_infra.capabilities.search.sync.cdc_sync_pipeline import CdcSyncPipeline  # noqa: E402
from web_infra.capabilities.search.sync.cdc_sync_registry import CdcSyncRegistry  # noqa: E402
from web_infra.capabilities.search.sync.es_cdc_sync_target import EsCdcSyncTarget  # noqa: E402


class _FakeTarget:
    """记录调用序列的内存目标（模拟 CdcSyncTargetInterface）"""

    def __init__(self) -> None:
        self.upserts: list[CdcChangeEvent] = []
        self.deletes: list[CdcChangeEvent] = []
        self.started = False
        self.stopped = False

    async def upsert(self, event: CdcChangeEvent) -> None:
        self.upserts.append(event)

    async def delete(self, event: CdcChangeEvent) -> None:
        self.deletes.append(event)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class _FakeOffsetStore:
    """内存位点存储"""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.saved: list[str] = []

    async def save(self, key: str, position: str) -> None:
        self.data[key] = position
        self.saved.append(key)

    async def load(self, key: str) -> str | None:
        return self.data.get(key)


class _FakeSource:
    """内存数据源（可注入事件供 Pipeline 消费）"""

    name = "mysql"

    def __init__(self) -> None:
        self.handler = None
        self.started = False
        self.stopped = False

    def subscribe(self, handler) -> None:
        self.handler = handler

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class _FakeSearchEngine:
    """记录写入的内存搜索引擎（模拟 SearchEngineInterface）"""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.created_indexes: list[tuple[str, str]] = []

    async def create_index(self, tenant_id, index_name, *, mappings=None, settings=None) -> None:
        self.created_indexes.append((tenant_id, index_name))

    async def index_document(self, tenant_id, index_name, doc_id, document, *, refresh=False) -> None:
        self.docs[doc_id] = {"tenant": tenant_id, "index": index_name, **document}

    async def delete_document(self, tenant_id, index_name, doc_id, *, refresh=False) -> None:
        self.docs.pop(doc_id, None)

    async def search(self, tenant_id, query):
        return []


def _event(op, *, table="t_order", pk=None, position=None, after=None, before=None):
    return CdcChangeEvent(
        "mysql", "shop", table, op, pk or {"id": "1"},
        before=before, after=after, position=position,
    )


# ---------------------------------------------------------------------------
# EsCdcSyncTarget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_es_target_upsert_insert_and_fields_projection():
    """upsert 写 doc_id 幂等，字段白名单/排除生效"""
    engine = _FakeSearchEngine()
    target = EsCdcSyncTarget(engine, mapping={"t_order": {"fields": ["id", "title"], "exclude": ["secret"]}})
    ev = _event(CdcOp.INSERT, after={"id": "1", "title": "苹果", "secret": "xx", "amount": 9})
    await target.upsert(ev)
    doc = engine.docs["1"]
    assert "title" in doc and "amount" not in doc and "secret" not in doc


@pytest.mark.asyncio
async def test_es_target_extract_tenant_and_soft_delete():
    """租户提取 + 软删标记（deleted=true）"""
    engine = _FakeSearchEngine()
    target = EsCdcSyncTarget(engine, mapping={"t_order": {"tenant_column": "tenant_id"}})
    ev = _event(CdcOp.UPDATE, pk={"id": "1"}, after={"id": "1", "tenant_id": "t1"})
    await target.upsert(ev)
    assert engine.docs["1"]["tenant"] == "t1"
    # 软删
    await target.delete(_event(CdcOp.DELETE, pk={"id": "1"}, after={"id": "1"}))
    assert engine.docs["1"]["deleted"] is True


@pytest.mark.asyncio
async def test_es_target_hard_delete_removes_doc():
    """硬删走 delete_document（文档被移除）"""
    engine = _FakeSearchEngine()
    target = EsCdcSyncTarget(engine, mapping={"t_order": {"delete_strategy": "hard"}})
    await target.upsert(_event(CdcOp.INSERT, after={"id": "1", "title": "x"}))
    await target.delete(_event(CdcOp.DELETE, pk={"id": "1"}))
    assert "1" not in engine.docs


# ---------------------------------------------------------------------------
# CdcSyncConfig
# ---------------------------------------------------------------------------


def test_sync_config_defaults():
    """默认配置：cdc/redis/mysql/soft"""
    cfg = CdcSyncConfig()
    assert cfg.enabled is False
    assert cfg.type == "cdc"
    assert cfg.source == "mysql"
    assert cfg.target == "es"
    assert cfg.offset_store == "redis"
    assert cfg.delete_strategy == "soft"


def test_sync_config_invalid_window_raises():
    """空闲窗口非法抛校验错误"""
    with pytest.raises(ValueError):
        CdcSyncConfig(reconcile={"window": [6, 2]})


# ---------------------------------------------------------------------------
# CdcSyncRegistry
# ---------------------------------------------------------------------------


def test_registry_register_and_override():
    """注册/覆盖/未注册 KeyError"""
    factory = lambda settings: None  # noqa: E731
    assert "redis" in CdcSyncRegistry.registered_offset_stores()
    CdcSyncRegistry.register_offset_store("my", factory)
    assert "my" in CdcSyncRegistry.registered_offset_stores()
    assert CdcSyncRegistry.get_offset_store("my") is factory
    # 覆盖
    factory2 = lambda settings: None  # noqa: E731
    CdcSyncRegistry.register_offset_store("my", factory2)
    assert CdcSyncRegistry.get_offset_store("my") is factory2
    with pytest.raises(KeyError):
        CdcSyncRegistry.get_offset_store("nonexistent")


# ---------------------------------------------------------------------------
# CdcSyncPipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_handles_events_and_advances_offset():
    """Pipeline 消费事件 → 目标写入 → 推进全局位点"""
    source = _FakeSource()
    target = _FakeTarget()
    offset = _FakeOffsetStore()
    pipeline = CdcSyncPipeline(
        source, target, offset, bulk_size=2, flush_interval_seconds=0.01, max_attempts=3,
    )
    await pipeline.start()
    # 注入事件
    await pipeline._handle_event(_event(CdcOp.INSERT, pk={"id": "1"}, position="binlog.1:100", after={"id": "1"}))
    await pipeline._handle_event(_event(CdcOp.INSERT, pk={"id": "2"}, position="binlog.1:200", after={"id": "2"}))
    await asyncio.sleep(0.05)  # 等待冲刷
    await pipeline.stop()
    assert len(target.upserts) == 2
    assert offset.saved  # 位点已推进
    latest = offset.data.get("mysql:shop:offset")
    assert latest == "binlog.1:200"


@pytest.mark.asyncio
async def test_pipeline_table_whitelist_filter():
    """表白名单过滤：非白名单表事件被忽略"""
    source = _FakeSource()
    target = _FakeTarget()
    offset = _FakeOffsetStore()
    pipeline = CdcSyncPipeline(source, target, offset, tables=["t_order"], flush_interval_seconds=0.01)
    await pipeline._handle_event(_event(CdcOp.INSERT, table="t_user", pk={"id": "9"}, after={"id": "9"}))
    assert "t_user" not in pipeline._pending
    assert len(target.upserts) == 0


@pytest.mark.asyncio
async def test_pipeline_write_failure_retries_then_raises_and_no_offset():
    """目标写入失败：重试后抛错（消费循环记录），位点不推进"""
    source = _FakeSource()
    target = _FakeTarget()

    class _FailingTarget(_FakeTarget):
        async def upsert(self, event):
            raise RuntimeError("es down")

    failing = _FailingTarget()
    offset = _FakeOffsetStore()
    pipeline = CdcSyncPipeline(source, failing, offset, max_attempts=2, backoff_base_seconds=0.01)
    await pipeline.start()
    await pipeline._handle_event(_event(CdcOp.INSERT, pk={"id": "1"}, position="binlog.1:100", after={"id": "1"}))
    await asyncio.sleep(0.05)
    await pipeline.stop()
    assert not offset.saved  # 失败不推进位点
