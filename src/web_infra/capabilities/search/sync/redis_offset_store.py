"""
Redis 位点存储

@Author: 花海
@Date: 2026/08/22 15:00
@Description: CDC 位点存储 Redis 实现（默认，搜索引擎数据同步方案 §5.3）：Hash 结构集中保存
              多个位点 key，field=位点 key，value=位点字符串；位点丢失可走空闲对账兜底。
              复用框架 Redis 连接（RedisConfig），多实例共享位点支持高可用。
"""
from __future__ import annotations

import logging
from typing import Any

from web_infra.capabilities.search.sync.cdc_offset_store_interface import CdcOffsetStoreInterface

logger = logging.getLogger("web_infra.capabilities.search.sync.redis_offset_store")

#: 位点 Hash 键（SEARCH_SYNC_OFFSET_KEY）
_DEFAULT_OFFSET_KEY = "web:search:sync:offsets"


class RedisOffsetStore(CdcOffsetStoreInterface):
    """Redis 位点存储（Hash 结构，多实例共享，默认实现）

    :param redis: redis.asyncio.Redis 兼容客户端（需提供 hset/hget 方法）
    :param key: 位点 Hash 键（缺省 web:search:sync:offsets）
    """

    def __init__(self, redis: Any, key: str = _DEFAULT_OFFSET_KEY) -> None:
        """初始化 Redis 位点存储。

        :param redis: redis.asyncio.Redis 兼容客户端
        :param key: 位点 Hash 键
        """
        self._redis = redis
        self._key = key
        self._name = "redis"

    @property
    def name(self) -> str:
        """数据源标识（供错误码/指标区分）"""
        return self._name

    async def save(self, key: str, position: str) -> None:
        """持久化位点（幂等覆盖进 Hash）"""
        await self._redis.hset(self._key, key, position)

    async def load(self, key: str) -> str | None:
        """读取位点；无记录返回 None"""
        value = await self._redis.hget(self._key, key)
        return str(value) if value is not None else None
