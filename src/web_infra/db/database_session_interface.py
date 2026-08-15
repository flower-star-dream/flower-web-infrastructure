"""
通用数据库会话接口

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 通用数据库会话接口（SPI），遵循规范 §3（接口与扩展机制）与 §10（数据访问）。
              一次数据库交互的最小单元，屏蔽 MySQL / PostgreSQL / SQLite 等具体数据库差异。
              SQL 使用命名参数（:name）+ 参数字典，各实现自行适配驱动占位符。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DatabaseSessionInterface(Protocol):
    """通用数据库会话接口：一次数据库交互的最小单元"""

    async def execute(self, sql: str, params: Any = None) -> int:
        """执行写操作，返回影响行数"""
        ...

    async def query_one(self, sql: str, params: Any = None) -> dict[str, Any] | None:
        """查询单行，返回字典或 None"""
        ...

    async def query_all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        """查询多行，返回字典列表"""
        ...

    async def commit(self) -> None:
        """提交事务"""
        ...

    async def rollback(self) -> None:
        """回滚事务"""
        ...

    async def close(self) -> None:
        """关闭会话（归还连接）"""
        ...
