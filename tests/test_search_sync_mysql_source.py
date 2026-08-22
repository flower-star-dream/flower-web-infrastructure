"""
搜索引擎同步：MySQL binlog 源转换测试

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 覆盖 MysqlBinlogCdcSource 的 binlog 事件转换（Write→INSERT、Update→UPDATE、
              Delete→DELETE）、主键提取（元数据主键列/疑似列/单列回退）、位点字符串构造与
              离线偏移读取。使用假 RowEvent 对象（SimpleNamespace），不依赖 mysql-replication 库
              （延迟导入：未安装时测试不触网，仅验证转换逻辑）。
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from web_infra.capabilities.search.sync.cdc_change_event import CdcOp  # noqa: E402
from web_infra.capabilities.search.sync.mysql_binlog_cdc_source import MysqlBinlogCdcSource  # noqa: E402


class _FakeOffsetStore:
    """内存位点存储（模拟 CdcOffsetStoreInterface）"""

    def __init__(self, position: str | None = None) -> None:
        self.position = position
        self.saved: list[tuple[str, str]] = []

    async def save(self, key: str, position: str) -> None:
        self.saved.append((key, position))

    async def load(self, key: str) -> str | None:
        return self.position


def _col(name: str, *, is_pk: bool = False) -> SimpleNamespace:
    return SimpleNamespace(name=name, column_name=name, primary_key=is_pk, is_primary=is_pk)


class _BaseEvent:
    """假 binlog 事件基类（提供 class name 用于类型判断）"""

    def __init__(self, schema="shop", table="t_order", rows=None, columns=None, timestamp=1700000000):
        self.schema = schema
        self.table = table
        self.rows = rows or []
        self.columns = columns
        self.timestamp = timestamp
        self.packet = SimpleNamespace(log_file="binlog.000001", log_pos=100)


class WriteRowsEvent(_BaseEvent):
    """假 WriteRowsEvent（类名需与 mysql-replication 库一致，供类型判断）"""


class UpdateRowsEvent(_BaseEvent):
    """假 UpdateRowsEvent"""


class DeleteRowsEvent(_BaseEvent):
    """假 DeleteRowsEvent"""


class TableMapEvent(_BaseEvent):
    """假 TableMapEvent（辅助事件）"""


def _write_event(rows=None, schema="shop", table="t_order", columns=None, timestamp=1700000000):
    return WriteRowsEvent(schema=schema, table=table, rows=rows, columns=columns, timestamp=timestamp)


def _update_event(rows=None):
    return UpdateRowsEvent(
        rows=rows or [{"before_values": {"id": "1", "title": "旧"}, "after_values": {"id": "1", "title": "新"}}],
        columns=[_col("id", is_pk=True)],
    )


def _delete_event(rows=None):
    return DeleteRowsEvent(
        rows=rows or [{"values": {"id": "1"}}],
        columns=[_col("id", is_pk=True)],
    )


def _make_source(position: str | None = None) -> MysqlBinlogCdcSource:
    return MysqlBinlogCdcSource({"host": "127.0.0.1"}, 10001, _FakeOffsetStore(position), database="shop")


# ---------------------------------------------------------------------------
# 事件转换
# ---------------------------------------------------------------------------


def test_convert_write_to_insert():
    """WriteRowsEvent → INSERT 事件（after=values，主键 id）"""
    src = _make_source()
    ev = src._to_change_event(_write_event(rows=[{"values": {"id": "1", "title": "苹果", "price": 9}}]))
    assert ev is not None
    assert ev.op == CdcOp.INSERT
    assert ev.primary_key == {"id": "1"}
    assert ev.after == {"id": "1", "title": "苹果", "price": 9}


def test_convert_update_to_update_with_before_after():
    """UpdateRowsEvent → UPDATE 事件（before/after 镜像）"""
    src = _make_source()
    ev = src._to_change_event(_update_event())
    assert ev.op == CdcOp.UPDATE
    assert ev.before == {"id": "1", "title": "旧"}
    assert ev.after == {"id": "1", "title": "新"}
    assert ev.primary_key == {"id": "1"}


def test_convert_delete_to_delete():
    """DeleteRowsEvent → DELETE 事件（主键 id）"""
    src = _make_source()
    ev = src._to_change_event(_delete_event())
    assert ev.op == CdcOp.DELETE
    assert ev.primary_key == {"id": "1"}


def test_convert_auxiliary_event_returns_none():
    """辅助事件（TableMapEvent 等）未匹配 → None"""
    src = _make_source()
    ev = src._to_change_event(TableMapEvent(schema="shop", table="t_order"))
    assert ev is None


# ---------------------------------------------------------------------------
# 主键提取
# ---------------------------------------------------------------------------


def test_primary_key_from_metadata_columns():
    """元数据主键列优先（column_schemas 的 primary_key 标记）"""
    src = _make_source()
    ev = src._to_change_event(
        _write_event(
            rows=[{"values": {"id": "7", "tenant_id": "t1", "title": "x"}}],
            columns=[_col("id", is_pk=True), _col("tenant_id", is_pk=False), _col("title")],
        )
    )
    assert ev.primary_key == {"id": "7"}


def test_primary_key_fallback_to_inferred():
    """无主键元数据时回退疑似主键列（id/{table}_id/以 id 结尾）"""
    src = _make_source()
    ev = src._to_change_event(
        _write_event(rows=[{"values": {"order_id": "88", "title": "x"}}], columns=[_col("order_id"), _col("title")])
    )
    assert ev.primary_key == {"order_id": "88"}


def test_primary_key_fallback_single_column():
    """单列行回退整行主键"""
    src = _make_source()
    ev = src._to_change_event(_write_event(rows=[{"values": {"only_col": "abc"}}], columns=[_col("only_col")]))
    assert ev.primary_key == {"only_col": "abc"}


# ---------------------------------------------------------------------------
# 位点
# ---------------------------------------------------------------------------


def test_position_string_from_packet():
    """位点字符串由 self._log_file/_log_pos 构造"""
    src = _make_source()
    src._log_file = "binlog.000001"
    src._log_pos = 100
    assert src._position_str(None) == "binlog.000001:100"


def test_load_offset_parses_position():
    """离线偏移：从位点存储解析 log_file/pos；无记录返回 (None, None)"""
    import asyncio

    src = _make_source(position="binlog.000123:456789")
    assert asyncio.run(src._load_offset()) == ("binlog.000123", 456789)

    src2 = _make_source(position=None)
    assert asyncio.run(src2._load_offset()) == (None, None)


def test_offset_key_aligns_lowercase_source():
    """位点 key 前缀 mysql:（与 pipeline 推进格式一致）"""
    src = _make_source()
    assert src._offset_key() == "mysql:shop:offset"
