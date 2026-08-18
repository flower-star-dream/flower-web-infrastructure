"""
MongoDB 数据库配置

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 基于 Beanie + PyMongo AsyncMongoClient 的异步文档数据库实现，遵循规范 §10（数据访问）。
              支持连接池、超时、心跳、重试等参数配置，延迟初始化客户端并通过 asyncio.Lock 保护并发。
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 仅静态检查使用，运行时跳过（延迟导入，最小安装不含 pymongo/beanie 时 import 本模块不失败）
    from beanie import init_beanie
    from pymongo import AsyncMongoClient
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from web_infra.logging import get_logger
from web_infra.monitoring.pool_metrics import record_mongo_pool_metrics

logger = get_logger("db.mongo")


class MongoDBConfig:
    """MongoDB 配置：管理异步客户端连接与 Beanie ODM 初始化"""

    def __init__(
        self,
        url: str = "mongodb://localhost:27017",
        database: str = "app",
        username: str | None = None,
        password: str | None = None,
        max_pool_size: int = 50,
        min_pool_size: int = 10,
        max_idle_time_ms: int = 600000,
        connect_timeout_ms: int = 10000,
        server_selection_timeout_ms: int = 30000,
        socket_timeout_ms: int = 60000,
        wait_queue_timeout_ms: int = 10000,
        heartbeat_frequency_ms: int = 10000,
        retry_writes: bool = True,
    ) -> None:
        """初始化 MongoDB 配置（仅保存参数，不立即建连）"""
        self.url = url
        self.database_name = database
        self.username = username
        self.password = password
        self.max_pool_size = max_pool_size
        self.min_pool_size = min_pool_size
        self.max_idle_time_ms = max_idle_time_ms
        self.connect_timeout_ms = connect_timeout_ms
        self.server_selection_timeout_ms = server_selection_timeout_ms
        self.socket_timeout_ms = socket_timeout_ms
        self.wait_queue_timeout_ms = wait_queue_timeout_ms
        self.heartbeat_frequency_ms = heartbeat_frequency_ms
        self.retry_writes = retry_writes
        self.client: AsyncMongoClient | None = None
        self._lock = asyncio.Lock()

    async def connect(self, document_models: list[type] | None = None) -> None:
        """建立连接并初始化 Beanie ODM（document_models 为 Document 模型类列表）。

        已连接时若传入模型则重新 init_beanie（覆盖注册模型，需调用方传全量）；
        并发建连由 asyncio.Lock 保护，幂等。
        """
        from beanie import init_beanie
        from pymongo import AsyncMongoClient
        from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

        async with self._lock:
            if self.client is not None:
                # 已连接：追加注册 Beanie Document 模型（重新 init_beanie 覆盖 document_models）
                if document_models:
                    await init_beanie(database=self.get_database(), document_models=document_models)
                return

            client_kwargs: dict[str, Any] = {
                "maxPoolSize": self.max_pool_size,
                "minPoolSize": self.min_pool_size,
                "maxIdleTimeMS": self.max_idle_time_ms,
                "connectTimeoutMS": self.connect_timeout_ms,
                "serverSelectionTimeoutMS": self.server_selection_timeout_ms,
                "socketTimeoutMS": self.socket_timeout_ms,
                "waitQueueTimeoutMS": self.wait_queue_timeout_ms,
                "heartbeatFrequencyMS": self.heartbeat_frequency_ms,
                "retryWrites": self.retry_writes,
            }
            if self.username is not None:
                client_kwargs["username"] = self.username
            if self.password is not None:
                client_kwargs["password"] = self.password

            client = AsyncMongoClient(self.url, **client_kwargs)
            try:
                # 触发服务器选择以尽早发现连接问题
                await client.admin.command("ping")
                db = client[self.database_name]
                if document_models:
                    await init_beanie(database=db, document_models=document_models)
                logger.info("mongodb_connected database=%s", self.database_name)
            except (ConnectionFailure, ServerSelectionTimeoutError) as e:
                await client.close()
                logger.error("mongodb_connection_failed error=%s", str(e))
                raise ConnectionFailure(f"MongoDB 连接失败: {e}") from e

            self.client = client

    async def close(self) -> None:
        """关闭客户端连接，释放连接池资源"""
        client: AsyncMongoClient | None = None
        async with self._lock:
            if self.client is not None:
                client = self.client
                self.client = None
        if client is not None:
            await client.close()
            logger.info("mongodb_disconnected")

    def get_database(self) -> Any:
        """获取数据库对象（未连接时抛 RuntimeError）"""
        if self.client is None:
            raise RuntimeError("MongoDB 未连接，请先调用 connect()")
        return self.client[self.database_name]

    async def health_check(self) -> bool:
        """检查 MongoDB 连接是否可用"""
        from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

        if self.client is None:
            return False
        try:
            await self.client.admin.command("ping")
            return True
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error("mongodb_health_check_failed error=%s", str(e))
            return False

    def update_pool_metrics(self) -> None:
        """刷新 MongoDB 连接池运行指标（§18.5.4，未连接时各项置 0）。

        供 /metrics 抓取前调用（health 端点统一刷新推送式指标）。
        双条件预警（§18.5）数据源：使用率由此处采集，时长条件由 monitoring/pool_alert 评估。
        """
        record_mongo_pool_metrics(self, "default")

    def __repr__(self) -> str:
        return (
            f"<MongoDBConfig database={self.database_name} "
            f"url={self.url.split('@')[-1] if '@' in self.url else self.url}>"
        )
