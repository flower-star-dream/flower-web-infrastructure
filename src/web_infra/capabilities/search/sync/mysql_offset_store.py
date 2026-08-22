"""
MySQL 位点存储

@Author: 花海
@Date: 2026/08/22 15:00
@Description: CDC 位点存储 MySQL 表实现（搜索引擎数据同步方案 §5.3）：源库 web_search_sync_offset 表
              集中保存位点（source/db/table 组合主键），与源库同库落盘可靠性高但实现较复杂；
              适用于强一致诉求场景。DDL/DML 由框架 db/versions 成对提供（V0.2.0 增量）。
              经框架数据库通用会话接口（DatabaseSessionInterface）执行，测试可用 SQLite 内存库验证。
"""
from __future__ import annotations

import logging
from typing import Any

from web_infra.capabilities.search.sync.cdc_offset_store_interface import CdcOffsetStoreInterface

logger = logging.getLogger("web_infra.capabilities.search.sync.mysql_offset_store")

#: 位点表名（与 db/versions/V0.2.0-search-sync-offset-ddl.sql 对齐）
_OFFSET_TABLE = "web_search_sync_offset"
_COLUMNS = "source, database_name, table_name, position, updated_at"


class MysqlOffsetStore(CdcOffsetStoreInterface):
    """MySQL 位点存储（源库表，组合主键 source/db/table）

    :param session_factory: 数据库会话工厂（调用返回 DatabaseSessionInterface 会话，
        与框架 MySQLDatabase/sqlite 会话均兼容）
    """

    def __init__(self, session_factory: Any) -> None:
        """初始化 MySQL 位点存储。

        :param session_factory: 数据库会话工厂（无参调用返回会话对象）
        """
        self._session_factory = session_factory
        self._name = "mysql"

    @property
    def name(self) -> str:
        """数据源标识（供错误码/指标区分）"""
        return self._name

    async def save(self, key: str, position: str) -> None:
        """持久化位点：拆分 key 为 source/db/table，按组合主键 upsert"""
        source, database, table = self._split_key(key)
        async with self._session_factory() as session:
            # 跨库兼容 upsert（MySQL/SQLite）：先查后写，避免 ON DUPLICATE KEY 方言差异
            row = await session.query_one(
                f"SELECT 1 FROM {_OFFSET_TABLE} WHERE source = :source "
                f"AND database_name = :database_name AND table_name = :table_name",
                {"source": source, "database_name": database, "table_name": table},
            )
            if row is None:
                await session.execute(
                    f"INSERT INTO {_OFFSET_TABLE} ({_COLUMNS}) "
                    f"VALUES (:source, :database_name, :table_name, :position, CURRENT_TIMESTAMP)",
                    {
                        "source": source,
                        "database_name": database,
                        "table_name": table,
                        "position": position,
                    },
                )
            else:
                await session.execute(
                    f"UPDATE {_OFFSET_TABLE} SET position = :position, updated_at = CURRENT_TIMESTAMP "
                    f"WHERE source = :source AND database_name = :database_name AND table_name = :table_name",
                    {
                        "source": source,
                        "database_name": database,
                        "table_name": table,
                        "position": position,
                    },
                )

    async def load(self, key: str) -> str | None:
        """读取位点；无记录返回 None"""
        source, database, table = self._split_key(key)
        async with self._session_factory() as session:
            row = await session.query_one(
                f"SELECT position FROM {_OFFSET_TABLE} WHERE source = :source "
                f"AND database_name = :database_name AND table_name = :table_name",
                {"source": source, "database_name": database, "table_name": table},
            )
        if row is None:
            return None
        value = row.get("position")
        return str(value) if value is not None else None

    # ------------------------------------------------------------------
    # 内部：位点 key 拆分
    # ------------------------------------------------------------------

    @staticmethod
    def _split_key(key: str) -> tuple[str, str, str]:
        """拆分位点 key "{source}:{database}:{table}" 为三元组。

        :raises ValueError: 段数不足 3（位点 key 必须含 source/db/table）
        """
        parts = key.split(":")
        if len(parts) < 3:
            raise ValueError(f"位点 key 必须含 source/database/table 三段: {key!r}")
        return parts[0], parts[1], ":".join(parts[2:])
