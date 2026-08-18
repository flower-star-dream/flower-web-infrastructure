"""
Beanie MongoDB 会话实现

@Author: 花海
@Date: 2026/08/18 10:00
@Description: MongoDB 默认实现（MongoSessionInterface 集合级契约），内部经 PyMongo AsyncCollection
              完成 CRUD（集合来自 MongoDBConfig.get_database()[name]），Beanie 角色为
              Document 模型管理与 init_beanie（ODM 初始化由 MongoDatabase.register_document_models 触发）。
              可选绑定事务会话（构造参数 mongo_session）：事务内所有操作自动携带事务 session，
              commit/rollback 委托 ClientSession 的事务管理；非事务会话 commit/rollback 为空操作。
              返回统一归一化：插入返回 _id 字符串、更新/删除返回计数。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 仅静态检查使用，运行时跳过（延迟导入，最小安装不含 pymongo 时 import 本模块不失败）
    from pymongo.asynchronous.client_session import AsyncClientSession

from web_infra.infra.logging import get_logger

logger = get_logger("db.mongo.session")


class BeanieMongoSession:
    """Beanie MongoDB 会话实现（MongoSessionInterface 集合级契约，Beanie + PyMongo 默认实现）"""

    def __init__(self, config: Any, mongo_session: Any = None) -> None:
        """初始化会话

        :param config: MongoDB 连接配置（提供 get_database()，返回 PyMongo Database 对象）
        :param mongo_session: 事务会话（AsyncClientSession，可选；事务内所有操作携带该 session）
        """
        self._config = config
        self._session = mongo_session

    def _collection(self, name: str) -> Any:
        """获取集合对象（AsyncCollection；未连接时由 config.get_database() 抛 RuntimeError）"""
        return self._config.get_database()[name]

    async def insert_one(self, collection: str, document: dict[str, Any]) -> str:
        """插入单条文档，返回 _id 字符串形式"""
        result = await self._collection(collection).insert_one(document, session=self._session)
        return str(result.inserted_id)

    async def insert_many(self, collection: str, documents: list[dict[str, Any]]) -> list[str]:
        """批量插入多条文档，返回 _id 字符串列表"""
        result = await self._collection(collection).insert_many(documents, session=self._session)
        return [str(_id) for _id in result.inserted_ids]

    async def find_one(
        self,
        collection: str,
        filter: dict[str, Any] | None = None,
        projection: Any = None,
        sort: Any = None,
    ) -> dict[str, Any] | None:
        """查询单条文档，返回 dict 或 None（无匹配）"""
        return await self._collection(collection).find_one(filter, projection, sort=sort, session=self._session)

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
        cursor = self._collection(collection).find(
            filter, projection, sort=sort, skip=skip, limit=limit, session=self._session
        )
        return await cursor.to_list(length=None)

    async def update_one(
        self,
        collection: str,
        filter: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
        array_filters: Any = None,
    ) -> int:
        """更新单条文档，返回实际修改条数（modified_count）"""
        result = await self._collection(collection).update_one(
            filter, update, upsert=upsert, array_filters=array_filters, session=self._session
        )
        return result.modified_count

    async def update_many(
        self,
        collection: str,
        filter: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
        array_filters: Any = None,
    ) -> int:
        """更新多条文档，返回实际修改条数"""
        result = await self._collection(collection).update_many(
            filter, update, upsert=upsert, array_filters=array_filters, session=self._session
        )
        return result.modified_count

    async def replace_one(
        self,
        collection: str,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        upsert: bool = False,
    ) -> int:
        """替换单条文档，返回实际修改条数"""
        result = await self._collection(collection).replace_one(
            filter, replacement, upsert=upsert, session=self._session
        )
        return result.modified_count

    async def delete_one(self, collection: str, filter: dict[str, Any]) -> int:
        """删除单条文档，返回删除条数（deleted_count）"""
        result = await self._collection(collection).delete_one(filter, session=self._session)
        return result.deleted_count

    async def delete_many(self, collection: str, filter: dict[str, Any]) -> int:
        """删除多条文档，返回删除条数"""
        result = await self._collection(collection).delete_many(filter, session=self._session)
        return result.deleted_count

    async def count(self, collection: str, filter: dict[str, Any] | None = None) -> int:
        """统计集合中匹配 filter 的文档条数"""
        return await self._collection(collection).count_documents(filter or {}, session=self._session)

    async def aggregate(self, collection: str, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """聚合管道查询，返回结果 dict 列表"""
        cursor = self._collection(collection).aggregate(pipeline, session=self._session)
        return await cursor.to_list(length=None)

    async def distinct(self, collection: str, key: str, filter: dict[str, Any] | None = None) -> list[Any]:
        """对指定字段去重，返回不同取值列表"""
        return await self._collection(collection).distinct(key, filter, session=self._session)

    async def create_index(
        self,
        collection: str,
        keys: Any,
        name: str | None = None,
        unique: bool = False,
    ) -> str:
        """创建索引，返回索引名"""
        return await self._collection(collection).create_index(keys, name=name, unique=unique, session=self._session)

    async def commit(self) -> None:
        """提交事务（非事务会话为空操作）"""
        if self._session is not None:
            await self._session.commit_transaction()

    async def rollback(self) -> None:
        """回滚事务（非事务会话为空操作）"""
        if self._session is not None:
            await self._session.abort_transaction()

    async def close(self) -> None:
        """关闭会话（连接池生命周期由工厂管理，此处无资源需释放；事务会话由 transaction 上下文管理）"""
        self._session = None
