"""
搜索引擎同步：事件模型与位点存储测试

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 覆盖 CdcChangeEvent 模型（操作枚举/文档 ID 稳定性/组合主键排序）、三种位点存储
              （Redis/File/MySQL）的 save/load/覆盖/损坏容错。
              File 用临时目录、MySQL 用 SQLite 内存库（SQL 通用子集）、Redis 用内存假客户端，均不触网。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from web_infra.capabilities.search.sync import CdcChangeEvent, CdcOp  # noqa: E402
from web_infra.capabilities.search.sync.file_offset_store import FileOffsetStore  # noqa: E402
from web_infra.capabilities.search.sync.mysql_offset_store import MysqlOffsetStore  # noqa: E402
from web_infra.capabilities.search.sync.redis_offset_store import RedisOffsetStore  # noqa: E402


class _FakeRedis:
    """内存 Redis 兼容假客户端（hset/hget）"""

    def __init__(self) -> None:
        self.h: dict[str, dict[str, str]] = {}

    async def hset(self, key: str, field: str, value: str) -> None:
        self.h.setdefault(key, {})[field] = value

    async def hget(self, key: str, field: str) -> str | None:
        return self.h.get(key, {}).get(field)


class _FakeSession:
    """SQLite 内存会话兼容（execute/query_one，伪装 DatabaseSessionInterface）"""

    def __init__(self, conn: object, cursor: object) -> None:
        self._conn = conn
        self._cursor = cursor
        self._committed = False

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def execute(self, sql: str, params: dict | None = None) -> int:
        self._cursor.execute(sql, params or {})
        return self._cursor.rowcount

    async def query_one(self, sql: str, params: dict | None = None) -> dict | None:
        self._cursor.execute(sql, params or {})
        row = self._cursor.fetchone()
        if row is None:
            return None
        return {d[0]: row[i] for i, d in enumerate(self._cursor.description or [])}


class _FakeSqliteStore:
    """SQLite 内存会话工厂（提供给 MysqlOffsetStore）"""

    def __init__(self) -> None:
        import sqlite3

        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE TABLE web_search_sync_offset (source TEXT, database_name TEXT, table_name TEXT, "
            "position TEXT, updated_at TEXT, PRIMARY KEY (source, database_name, table_name))"
        )
        self.conn.commit()
        self._factory = self

    def __call__(self) -> _FakeSession:
        conn = self.conn
        cursor = conn.cursor()
        return _FakeSession(conn, cursor)


# ---------------------------------------------------------------------------
# CdcChangeEvent 模型
# ---------------------------------------------------------------------------


def test_change_event_document_id_stable():
    """文档 ID 稳定且组合主键按列序拼接"""
    ev = CdcChangeEvent(
        source="mysql", database="shop", table="t_order", op=CdcOp.INSERT,
        primary_key={"id": "1001", "tenant": "t1"}, after={"id": "1001", "title": "苹果"},
    )
    # 组合主键按列名字典序拼接（id < tenant）
    assert ev.document_id == "1001_t1"
    # 重复构造 ID 稳定
    ev2 = CdcChangeEvent("mysql", "shop", "t_order", CdcOp.INSERT, {"id": "1001", "tenant": "t1"})
    assert ev.document_id == ev2.document_id


def test_change_event_ops_enum():
    """操作枚举取值"""
    assert CdcOp.INSERT.value == "insert"
    assert CdcOp.UPDATE.value == "update"
    assert CdcOp.DELETE.value == "delete"


def test_change_event_repr_no_sensitive():
    """repr 不含业务字段值（防敏感数据入日志）"""
    ev = CdcChangeEvent("mysql", "shop", "t_order", CdcOp.UPDATE, {"id": "1"}, after={"secret": "xx"})
    assert "xx" not in repr(ev)
    assert "t_order" in repr(ev)


# ---------------------------------------------------------------------------
# Redis 位点存储
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_offset_store_roundtrip():
    """Redis 位点 save/load/覆盖"""
    store = RedisOffsetStore(_FakeRedis())
    assert store.name == "redis"
    assert await store.load("mysql:shop:offset") is None
    await store.save("mysql:shop:offset", "binlog.000123:456789")
    assert await store.load("mysql:shop:offset") == "binlog.000123:456789"
    await store.save("mysql:shop:offset", "binlog.000124:10")
    assert await store.load("mysql:shop:offset") == "binlog.000124:10"


# ---------------------------------------------------------------------------
# File 位点存储
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_offset_store_roundtrip():
    """File 位点 save/load/覆盖，落在临时文件"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "offsets.json"
        store = FileOffsetStore(path)
        assert store.name == "file"
        assert await store.load("mysql:shop:offset") is None
        await store.save("mysql:shop:offset", "binlog.000123:456789")
        await store.save("mysql:other:offset", "binlog.000123:11")
        assert await store.load("mysql:shop:offset") == "binlog.000123:456789"
        assert path.exists()
        # 覆盖
        await store.save("mysql:shop:offset", "binlog.000200:99")
        assert await store.load("mysql:shop:offset") == "binlog.000200:99"


@pytest.mark.asyncio
async def test_file_offset_store_corrupt_returns_none(tmp_path: Path):
    """File 位点文件损坏时读返回 None（走全量对账兜底）"""
    path = tmp_path / "offsets.json"
    path.write_text("{not-json", encoding="utf-8")
    store = FileOffsetStore(path)
    assert await store.load("mysql:shop:offset") is None


# ---------------------------------------------------------------------------
# MySQL 位点存储（SQLite 内存库）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mysql_offset_store_roundtrip():
    """MySQL 位点 save/load/覆盖（SQLite 内存库验证 SQL 语义）"""
    store = MysqlOffsetStore(_FakeSqliteStore())
    assert store.name == "mysql"
    assert await store.load("mysql:shop:t_order") is None
    await store.save("mysql:shop:t_order", "binlog.000123:456789")
    assert await store.load("mysql:shop:t_order") == "binlog.000123:456789"
    await store.save("mysql:shop:t_order", "binlog.000200:99")
    assert await store.load("mysql:shop:t_order") == "binlog.000200:99"


def test_mysql_offset_split_key():
    """位点 key 拆分：不足三段抛 ValueError"""
    store = MysqlOffsetStore(_FakeSqliteStore())
    assert store._split_key("mysql:shop:t_order") == ("mysql", "shop", "t_order")
    with pytest.raises(ValueError):
        store._split_key("mysql:shop")
