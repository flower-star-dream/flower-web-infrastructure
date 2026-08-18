"""
MongoDB 通用数据库实现

@Author: 花海
@Date: 2026/08/18 10:00
@Description: MongoDB 的默认数据库工厂实现（MongoDatabaseFactoryInterface），基于 MongoDBConfig + Beanie。
              提供统一会话入口（规范 §10 数据访问）：
              - session()：通用 MongoDB 会话（MongoSessionInterface 集合级契约），业务只依赖通用接口，
                屏蔽 Beanie / PyMongo 原生 API，便于后续替换其他文档数据库实现；
              - register_document_models()：注册 Beanie Document 模型并初始化 ODM（业务可选，
                未注册时仅降级为集合级访问，纯 PyMongo 也可用）；
              - transaction()：多文档事务上下文（需 MongoDB 副本集）。
              连接惰性：首次 create_session / register_document_models / transaction / health_check 时建连。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncGenerator

if TYPE_CHECKING:  # 仅静态检查使用，运行时跳过（延迟导入）
    from web_infra.capabilities.db.mongodb_config import MongoDBConfig

from web_infra.capabilities.db.beanie_mongo_session import BeanieMongoSession
from web_infra.capabilities.db.mongo_database_factory_interface import MongoDatabaseFactoryInterface
from web_infra.capabilities.db.mongo_session_interface import MongoSessionInterface


class MongoDatabase:
    """MongoDB 默认数据库实现（MongoDatabaseFactoryInterface，Beanie + PyMongo）"""

    def __init__(self, config: MongoDBConfig) -> None:
        """初始化 MongoDB 数据库工厂

        :param config: MongoDB 连接配置（连接管理 + Beanie ODM 初始化）
        """
        self._config = config
        # 已注册的 Beanie Document 模型（业务经 register_document_models 注册，惰性初始化 ODM）
        self._document_models: set[type] = set()
        # 已完成 ODM 初始化的模型集合（增量注册时仅在新增模型时重新 init_beanie）
        self._initialized_models: set[type] = set()

    async def _ensure_connected(self) -> None:
        """确保客户端已连接且已注册模型完成 ODM 初始化（连接与 ODM 初始化均惰性）"""
        if self._config.client is None:
            await self._config.connect(document_models=list(self._document_models) or None)
            self._initialized_models = set(self._document_models)
        elif self._document_models and self._document_models != self._initialized_models:
            await self._config.connect(document_models=list(self._document_models))
            self._initialized_models = set(self._document_models)

    async def create_session(self) -> MongoSessionInterface:
        """创建通用 MongoDB 会话（自动确保已连接并初始化 ODM）"""
        await self._ensure_connected()
        return BeanieMongoSession(self._config)

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[MongoSessionInterface, None]:
        """MongoDB 会话上下文管理器（规范 §10 数据访问：框架统一管理连接生命周期，业务无需 try/finally）。

        进入创建会话，退出自动提交（异常回滚）并关闭；单文档操作本身原子，无需显式事务。
        """
        session = await self.create_session()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[MongoSessionInterface, None]:
        """多文档事务上下文（需 MongoDB 副本集；单机/无副本集时 start_transaction 抛 OperationFailure）。

        事务内会话所有操作自动携带事务 session，退出自动提交（异常自动中止）并释放事务会话；
        业务无需手动 commit/rollback（需显式控制时可用会话的 commit()/rollback()）。
        """
        await self._ensure_connected()
        client = self._config.client
        async with await client.start_session() as mongo_session:
            async with mongo_session.start_transaction():
                yield BeanieMongoSession(self._config, mongo_session)

    async def register_document_models(self, models: list[type]) -> None:
        """注册 Beanie Document 模型并初始化 ODM（可多次调用，幂等追加）。

        :param models: Beanie Document 模型类列表（业务模型经 init_beanie 注册后可用 ODM 类方法）
        """
        self._document_models.update(models)
        await self._ensure_connected()

    async def close(self) -> None:
        """关闭客户端连接，释放连接池资源"""
        await self._config.close()
        self._initialized_models.clear()

    async def health_check(self) -> bool:
        """健康检查（ping）"""
        return await self._config.health_check()

    def get_database(self) -> Any:
        """获取原生数据库对象（未连接时抛 RuntimeError）"""
        return self._config.get_database()

    def get_collection(self, name: str) -> Any:
        """获取原生集合对象（未连接时抛 RuntimeError）"""
        return self._config.get_database()[name]

    def update_pool_metrics(self) -> None:
        """刷新 MongoDB 连接池运行指标（代理到配置，供 /metrics 抓取调用）"""
        self._config.update_pool_metrics()
