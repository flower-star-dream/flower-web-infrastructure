"""
Redis 数据库配置

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 基于 redis-py 的 Redis 异步连接管理（Redis 本质为数据库，故归入 db 模块）。
              支持连接池、超时、解码、keepalive、健康检查等参数，延迟连接并通过 asyncio.Lock 保护并发。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅静态检查使用，运行时跳过（延迟导入，最小安装不含 redis-py 时 import 本模块不失败）
    from redis.asyncio import Redis
    from redis.exceptions import RedisError

from web_infra.logging import get_logger
from web_infra.monitoring.pool_metrics import record_redis_pool_metrics

logger = get_logger("db.redis")


class RedisConfig:
    """Redis 配置：管理异步 Redis 连接池"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        username: str | None = None,
        max_connections: int = 50,
        decode_responses: bool = True,
        socket_connect_timeout: int = 5,
        socket_timeout: int = 5,
        socket_keepalive: bool = True,
        health_check_interval: int = 30,
        retry_on_timeout: bool = True,
    ) -> None:
        """初始化 Redis 配置（仅保存参数，不立即建连）"""
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.username = username
        self.max_connections = max_connections
        self.decode_responses = decode_responses
        self.socket_connect_timeout = socket_connect_timeout
        self.socket_timeout = socket_timeout
        self.socket_keepalive = socket_keepalive
        self.health_check_interval = health_check_interval
        self.retry_on_timeout = retry_on_timeout
        self._redis: Redis | None = None
        self._lock = asyncio.Lock()
        # 同步客户端锁（跨线程保护 _redis 创建；connect 的协程级互斥仍由 _lock 负责）
        self._sync_lock = threading.Lock()

    def client(self) -> Redis:
        """获取可用的异步客户端实例（未连接时同步创建，首次 IO 自动建连）。

        供中间件装配等同步上下文复用 Redis 客户端（如幂等存储经 cache 组件配置获取）；
        不强制 ping（避免同步装配阻塞），连接管理与健康检查仍归 connect/close 负责。
        双重检查锁定（_sync_lock）：跨线程并发调用时只创建一份客户端实例（与 connect 的
        协程级互斥 _lock 对称，connect 内部亦复用本方法）。
        """
        if self._redis is None:
            with self._sync_lock:
                if self._redis is None:
                    from redis.asyncio import Redis

                    self._redis = Redis(
                        host=self.host,
                        port=self.port,
                        db=self.db,
                        password=self.password,
                        username=self.username,
                        max_connections=self.max_connections,
                        decode_responses=self.decode_responses,
                        socket_connect_timeout=self.socket_connect_timeout,
                        socket_timeout=self.socket_timeout,
                        socket_keepalive=self.socket_keepalive,
                        health_check_interval=self.health_check_interval,
                        retry_on_timeout=self.retry_on_timeout,
                    )
        return self._redis

    async def connect(self) -> Redis:
        """建立 Redis 连接，返回异步客户端实例（连接失败抛 RedisError）"""
        from redis.exceptions import RedisError

        async with self._lock:
            if self._redis is not None:
                return self._redis

            redis = self.client()
            try:
                # 触发连接以尽早发现配置问题
                await redis.ping()
                logger.info("redis_connected host=%s port=%s db=%s", self.host, self.port, self.db)
            except RedisError as e:
                logger.error("redis_connection_failed host=%s port=%s error=%s", self.host, self.port, str(e))
                raise

            return self._redis

    async def close(self) -> None:
        """关闭 Redis 连接，释放连接池资源"""
        redis: Redis | None = None
        async with self._lock:
            if self._redis is not None:
                redis = self._redis
                self._redis = None
        if redis is not None:
            await redis.close()
            logger.info("redis_disconnected")

    @property
    def redis(self) -> Redis:
        """获取 Redis 客户端实例（未连接时抛 RuntimeError）"""
        if self._redis is None:
            raise RuntimeError("Redis 未连接，请先调用 connect()")
        return self._redis

    async def health_check(self) -> bool:
        """检查 Redis 连接是否可用"""
        from redis.exceptions import RedisError

        if self._redis is None:
            return False
        try:
            await self._redis.ping()
            return True
        except RedisError as e:
            logger.error("redis_health_check_failed error=%s", str(e))
            return False

    def update_pool_metrics(self) -> None:
        """刷新 Redis 连接池运行指标（§18.5.4，未连接时各项置 0）。

        供 /metrics 抓取前调用（health 端点统一刷新推送式指标）。
        双条件预警（§18.5）数据源：使用率由此处采集，时长条件由 monitoring/pool_alert 评估。
        """
        record_redis_pool_metrics(self._redis, "default")

    def __repr__(self) -> str:
        return f"<RedisConfig host={self.host}:{self.port} db={self.db}>"
