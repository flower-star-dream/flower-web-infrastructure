"""
Redis 缓存后端

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 基于 RedisConfig 的分布式缓存后端，实现 CacheBackendInterface 抽象（get/set/delete/exists），
              遵循规范 §8（缓存全生命周期）。Redis 本质为数据库，故其连接管理归入 db 模块；
              连接管理委托给 RedisConfig（connect/close/health_check）。
              缓存 Key 需带版本与业务域前缀，可配合 KeyBuilder 使用（规范 §5.7）。
              支持空值占位（规范 §8.2 防缓存穿透，独立 #empty Key 存储）与
              TTL 抖动（规范 §8.3 防缓存雪崩）。
"""
from __future__ import annotations

import random
from typing import Any

from web_infra.cache.cache_backend_interface import EMPTY_TTL_LIMIT_SECONDS, CacheBackendInterface
from web_infra.db.redis_config import RedisConfig
from web_infra.monitoring.cache_metrics import CacheMetrics

# 缓存实现名（低基数标签，对应 app.cache.type）
_CACHE_NAME = "redis"

# 空值占位 Key 后缀（与真实缓存 Key 隔离，避免与业务值类型/内容冲突）
_EMPTY_KEY_SUFFIX = "#empty"


class RedisCacheBackend(CacheBackendInterface):
    """Redis 分布式缓存后端（实现 CacheBackendInterface 抽象）

    存储值为字符串/字节等基础类型，复杂对象需调用方序列化后存储。
    """

    def __init__(
        self,
        config: RedisConfig | None = None,
        key_prefix: str = "web:",
        default_ttl_jitter_seconds: float = 0.0,
    ) -> None:
        """初始化 Redis 缓存后端。

        :param config: Redis 连接配置（默认本地 RedisConfig）
        :param key_prefix: 缓存 Key 前缀（带版本/业务域，规范 §5.7）
        :param default_ttl_jitter_seconds: 默认 TTL 抖动上限（秒，0 关闭；规范 §8.3 防雪崩）
        """
        self._config = config or RedisConfig()
        self._key_prefix = key_prefix
        self._default_ttl_jitter_seconds = default_ttl_jitter_seconds

    async def _redis(self) -> Any:
        """懒连接并返回 Redis 客户端"""
        return await self._config.connect()

    def _key(self, key: str) -> str:
        """拼接 Key 前缀（带版本/业务域，规范 §5.7）"""
        return self._key_prefix + key

    def _empty_key(self, key: str) -> str:
        """拼接空值占位 Key（真实 Key 附加 #empty 后缀，隔离存储）"""
        return self._key_prefix + key + _EMPTY_KEY_SUFFIX

    async def get(self, key: str) -> Any | None:
        client = await self._redis()
        value = await client.get(self._key(key))
        CacheMetrics.record_operation(_CACHE_NAME, "get", hit=value is not None)
        return value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        ttl_jitter_seconds: float | None = None,
    ) -> None:
        """写入缓存。

        :param ttl: 过期秒数（None 不过期）
        :param ttl_jitter_seconds: TTL 抖动上限（秒，None 使用构造默认，0 关闭；规范 §8.3 防雪崩）
        """
        ex: int | None = ttl
        jitter = (
            self._default_ttl_jitter_seconds
            if ttl_jitter_seconds is None
            else ttl_jitter_seconds
        )
        if ex is not None and jitter > 0:
            # 抖动叠加 [0, jitter) 秒后取整，使同 TTL 的热点 Key 错峰过期（规范 §8.3）
            ex = int(ex + random.uniform(0, jitter))
        client = await self._redis()
        await client.set(self._key(key), value, ex=ex)
        CacheMetrics.record_operation(_CACHE_NAME, "set")

    async def delete(self, key: str) -> None:
        client = await self._redis()
        # 同步删除真实缓存与空值占位，避免残留空值标记（规范 §8.2）
        await client.delete(self._key(key), self._empty_key(key))
        CacheMetrics.record_operation(_CACHE_NAME, "delete")

    async def exists(self, key: str) -> bool:
        client = await self._redis()
        result = bool(await client.exists(self._key(key)))
        CacheMetrics.record_operation(_CACHE_NAME, "exists", hit=result)
        return result

    async def set_empty(self, key: str, ttl: int = 60) -> None:
        """写入空值占位（数据不存在标记，规范 §8.2 防缓存穿透）。

        :param ttl: 过期秒数（默认 60，上限 120s，超限自动钳制）
        """
        ttl = min(max(int(ttl), 1), EMPTY_TTL_LIMIT_SECONDS)
        client = await self._redis()
        await client.set(self._empty_key(key), "1", ex=ttl)
        CacheMetrics.record_operation(_CACHE_NAME, "set_empty")

    async def is_empty(self, key: str) -> bool:
        """判断是否处于空值占位状态（TTL 过期后自动失效返回 False）"""
        client = await self._redis()
        result = bool(await client.exists(self._empty_key(key)))
        CacheMetrics.record_operation(_CACHE_NAME, "is_empty", hit=result)
        return result

    async def close(self) -> None:
        """关闭连接池"""
        await self._config.close()

    def update_pool_metrics(self) -> None:
        """刷新 Redis 连接池运行指标（代理到配置，供 /metrics 抓取调用）"""
        self._config.update_pool_metrics()
