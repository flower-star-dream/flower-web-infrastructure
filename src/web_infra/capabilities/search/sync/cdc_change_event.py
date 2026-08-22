"""
CDC 变更事件模型

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 数据库变更事件统一模型（搜索引擎数据同步方案 §4.2）：各数据源差异在此收敛，
              下游（Pipeline/目标）不感知来源。primary_key 用于生成稳定 ES 文档 ID，
              before/after 为字段字典（None 表示镜像不可用），position 为数据源位点描述透传不解析。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any


class CdcOp(str, Enum):
    """变更操作类型"""

    INSERT = "insert"  # 新增
    UPDATE = "update"  # 修改（含 before/after）
    DELETE = "delete"  # 删除


class CdcChangeEvent:
    """数据库变更事件（统一模型，数据源差异在此收敛）

    :param source: 数据源标识（如 "mysql"）
    :param database: 数据库名（源库）
    :param table: 数据表名
    :param op: 变更操作类型（新增/修改/删除）
    :param primary_key: 主键键值（如 {"id": "1001"}），用于生成稳定 ES 文档 ID
    :param before: 变更前镜像（None 表示不可用，如 INSERT 无 before）
    :param after: 变更后镜像（None 表示不可用，如 DELETE 视源而定）
    :param position: 数据源位点描述（如 "binlog.000123:456789"），透传不解析
    :param ts: 变更发生时间（binlog 时间戳，UTC）
    """

    __slots__ = ("source", "database", "table", "op", "primary_key", "before", "after", "position", "ts")

    def __init__(
        self,
        source: str,
        database: str,
        table: str,
        op: CdcOp,
        primary_key: dict[str, Any],
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        position: str | None = None,
        ts: datetime | None = None,
    ) -> None:
        """初始化变更事件。

        :param source: 数据源标识
        :param database: 数据库名
        :param table: 数据表名
        :param op: 变更操作类型
        :param primary_key: 主键键值
        :param before: 变更前镜像（None 表示不可用）
        :param after: 变更后镜像（None 表示不可用）
        :param position: 数据源位点描述
        :param ts: 变更发生时间（UTC）
        """
        self.source = source
        self.database = database
        self.table = table
        self.op = op
        self.primary_key = dict(primary_key)
        self.before = before
        self.after = after
        self.position = position
        self.ts = ts

    @property
    def document_id(self) -> str:
        """生成稳定的目标文档 ID（主键按列序拼接）。

        组合主键按列名字典序拼接，保证同一业务文档 ID 稳定可幂等覆盖。
        """
        return "_".join(str(self.primary_key[k]) for k in sorted(self.primary_key))

    def __repr__(self) -> str:  # pragma: no cover - 仅供日志调试，不参与逻辑
        """调试用：标识事件来源与主键，不含业务字段值（防敏感数据入日志）"""
        return (
            f"<CdcChangeEvent source={self.source} db={self.database} "
            f"table={self.table} op={self.op.value} pk={self.primary_key}>"
        )
