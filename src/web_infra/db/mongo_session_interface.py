"""
MongoDB 通用会话接口

@Author: 花海
@Date: 2026/08/18 10:00
@Description: MongoDB 通用会话接口（SPI），遵循规范 §3（接口与扩展机制）与 §10（数据访问）。
              一次文档数据库交互的最小单元，屏蔽 Beanie / PyMongo / 其他 ODM 的具体差异。
              契约采用「集合名 + dict 文档/filter」的集合级通用形态（对齐关系型
              DatabaseSessionInterface 的 SQL 通用契约思路），任何文档型数据库实现均可接入；
              filter / update / pipeline 等操作条件沿用 MongoDB 查询语法（与驱动一致）。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MongoSessionInterface(Protocol):
    """通用 MongoDB 会话接口：一次文档数据库交互的最小单元（集合级契约）"""

    async def insert_one(self, collection: str, document: dict[str, Any]) -> str:
        """插入单条文档，返回 _id 的字符串形式"""
        ...

    async def insert_many(self, collection: str, documents: list[dict[str, Any]]) -> list[str]:
        """批量插入多条文档，返回 _id 字符串列表"""
        ...

    async def find_one(
        self,
        collection: str,
        filter: dict[str, Any] | None = None,
        projection: Any = None,
        sort: Any = None,
    ) -> dict[str, Any] | None:
        """查询单条文档，返回 dict 或 None（无匹配）"""
        ...

    async def find_many(
        self,
        collection: str,
        filter: dict[str, Any] | None = None,
        projection: Any = None,
        sort: Any = None,
        skip: int = 0,
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        """查询多条文档，返回 dict 列表（limit<=0 表示不限制数量）"""
        ...

    async def update_one(
        self,
        collection: str,
        filter: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
        array_filters: Any = None,
    ) -> int:
        """更新单条文档，返回实际修改条数（modified_count；upsert 插入场景为 0）"""
        ...

    async def update_many(
        self,
        collection: str,
        filter: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
        array_filters: Any = None,
    ) -> int:
        """更新多条文档，返回实际修改条数"""
        ...

    async def replace_one(
        self,
        collection: str,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        upsert: bool = False,
    ) -> int:
        """替换单条文档，返回实际修改条数"""
        ...

    async def delete_one(self, collection: str, filter: dict[str, Any]) -> int:
        """删除单条文档，返回删除条数（deleted_count）"""
        ...

    async def delete_many(self, collection: str, filter: dict[str, Any]) -> int:
        """删除多条文档，返回删除条数"""
        ...

    async def count(self, collection: str, filter: dict[str, Any] | None = None) -> int:
        """统计集合中匹配 filter 的文档条数"""
        ...

    async def aggregate(self, collection: str, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """聚合管道查询，返回结果 dict 列表"""
        ...

    async def distinct(self, collection: str, key: str, filter: dict[str, Any] | None = None) -> list[Any]:
        """对指定字段去重，返回不同取值列表"""
        ...

    async def create_index(
        self,
        collection: str,
        keys: Any,
        name: str | None = None,
        unique: bool = False,
    ) -> str:
        """创建索引，返回索引名"""
        ...

    async def commit(self) -> None:
        """提交事务（非事务会话为空操作）"""
        ...

    async def rollback(self) -> None:
        """回滚事务（非事务会话为空操作）"""
        ...

    async def close(self) -> None:
        """关闭会话（归还连接；连接池生命周期由工厂管理）"""
        ...
