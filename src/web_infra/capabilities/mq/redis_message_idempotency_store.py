"""
Redis 消息幂等键存储

@Author: 花海
@Date: 2026/08/14 19:00
@Description: 基于 Redis SETNX 的消息消费幂等键存储（多实例场景，规范 §9.2：缓存 SETNX 保证跨实例原子性，
              幂等键保留 7 天覆盖投递重试窗口）。
              整改 S5-4（2026-08-15）：Redis Key 统一经 CacheKeyBuilder 模板生成
              （web:mq:v1:msg_idem:{key}，符合 §5.7 web:{module}:v1:{biz}），禁止手写 `前缀+key` 拼接。
              注意：键格式变更会破坏既有 Redis 存量键，属预期整改（业务需容忍旧键自然过期）。
"""
from __future__ import annotations

from typing import Any

from web_infra.infra.constants.cache_key import CacheKeyBuilder
from web_infra.capabilities.mq.message_idempotency_store_interface import MessageIdempotencyStoreInterface


class RedisMessageIdempotencyStore(MessageIdempotencyStoreInterface):
    """Redis 消息消费幂等键存储（跨实例原子性）"""

    def __init__(self, redis: Any) -> None:
        """初始化存储。

        :param redis: redis.asyncio.Redis 兼容客户端（需提供 set/delete）
        """
        self._redis = redis

    def _idem_key(self, key: str) -> str:
        """生成消息消费幂等键（整改 S5-4：统一经 CacheKeyBuilder 模板，含 v1 版本段）"""
        return CacheKeyBuilder.build(CacheKeyBuilder.MESSAGE_IDEMPOTENCY, key=key)

    async def try_consume(self, key: str, ttl_seconds: int) -> bool:
        """SET NX 原子写入（首次消费成功，重复消费返回 False）"""
        return bool(await self._redis.set(self._idem_key(key), "1", nx=True, ex=ttl_seconds))

    async def release(self, key: str) -> None:
        """回滚占用（业务失败重试）"""
        await self._redis.delete(self._idem_key(key))
