"""
搜索引擎同步：端到端串联测试

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 覆盖 Pipeline → EsCdcSyncTarget → InMemorySearchEngine 的端到端串联：
              事件注入 → 攒批写内存搜索 → 位点推进；并对账服务用同一目标补齐（幂等）。
              验证「写库 → 同步 → 可检索」链路正确性（内存实现，零外部依赖）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from web_infra.capabilities.search.in_memory_search_engine import InMemorySearchEngine  # noqa: E402
from web_infra.capabilities.search.sync.cdc_change_event import CdcChangeEvent, CdcOp  # noqa: E402
from web_infra.capabilities.search.sync.cdc_sync_pipeline import CdcSyncPipeline  # noqa: E402
from web_infra.capabilities.search.sync.es_cdc_sync_target import EsCdcSyncTarget  # noqa: E402
from web_infra.capabilities.search.sync.full_reconcile_service import FullReconcileService  # noqa: E402
from web_infra.capabilities.search.search_query import SearchQuery  # noqa: E402


class _MemorySource:
    """内存数据源（name=mysql，事件经 handler 注入）"""

    name = "mysql"

    def __init__(self) -> None:
        self.handler = None

    def subscribe(self, handler) -> None:
        self.handler = handler

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class _MemoryOffsetStore:
    """内存位点存储"""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def save(self, key: str, position: str) -> None:
        self.data[key] = position

    async def load(self, key: str) -> str | None:
        return self.data.get(key)


def _insert_event(pk, title, position):
    return CdcChangeEvent("mysql", "shop", "t_order", CdcOp.INSERT, {"id": pk}, after={"id": pk, "title": title}, position=position)


@pytest.mark.asyncio
async def test_sync_to_search_and_reconcile():
    """端到端：事件经 Pipeline 同步到内存搜索，对账补齐（幂等）"""
    engine = InMemorySearchEngine()
    target = EsCdcSyncTarget(engine, mapping={"t_order": {"index": "orders"}})
    offset = _MemoryOffsetStore()
    source = _MemorySource()
    pipeline = CdcSyncPipeline(source, target, offset, flush_interval_seconds=0.01)

    await pipeline.start()
    # 注入两条 INSERT（分属不同 position）
    await pipeline._handle_event(_insert_event("p1", "苹果手机", "binlog.1:100"))
    await pipeline._handle_event(_insert_event("p2", "华为平板", "binlog.1:200"))
    await asyncio.sleep(0.05)
    await pipeline.stop()

    # 检索命中（内存索引名 orders，符合命名规范）
    hits = await engine.search(None, SearchQuery(keyword="苹果", index_name="orders"))
    assert any(h.id == "p1" for h in hits)
    # 位点推进
    assert offset.data.get("mysql:shop:offset") == "binlog.1:200"

    # 对账补齐（库记录更多，幂等覆盖）：p3 缺失，对账后补齐
    reader_called = 0

    async def row_reader(table, batch_size, offset):
        nonlocal reader_called
        if reader_called == 0:
            reader_called += 1
            return [{"id": "p1", "title": "苹果手机"}, {"id": "p2", "title": "华为平板"}, {"id": "p3", "title": "小米"}]
        return []

    service = FullReconcileService(target, row_reader, required_id_column="id", batch_size=10)
    result = await service.reconcile("t_order")
    assert result["scanned"] == 3
    hits2 = await engine.search(None, SearchQuery(keyword="小米", index_name="orders"))
    assert any(h.id == "p3" for h in hits2)
