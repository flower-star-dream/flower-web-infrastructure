"""
Redis 幂等键存储

@Author: 花海
@Date: 2026/08/14 18:30
@Description: 基于 Redis 的幂等键存储（多实例场景，规范 §12.6）：
              SET NX 原子占用 + 结果序列化存储，TTL 覆盖重试窗口（如 24h）。
              整改 S5-4（2026-08-15）：Redis Key 统一经 CacheKeyBuilder 模板生成
              （web:idem:v1:{occupy|result}:{key}，符合 §5.7 web:{module}:v1:{biz}），
              禁止手写 `前缀+key` 拼接。注意：键格式变更会破坏既有 Redis 存量键，
              属预期整改（基础设施库，业务需在升级时容忍旧键自然过期）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from web_infra.constants.cache_key import CacheKeyBuilder
from web_infra.web.idempotency_store_interface import IdempotencyResult, IdempotencyStoreInterface


class RedisIdempotencyStore(IdempotencyStoreInterface):
    """Redis 幂等键存储（跨实例原子性，规范 §12.6 服务端幂等表/分布式锁保障）"""

    def __init__(self, redis: Any) -> None:
        """初始化存储。

        :param redis: redis.asyncio.Redis 兼容客户端（需提供 set/get/hset/hget/expire/delete）
        """
        self._redis = redis

    def _occupy_key(self, key: str) -> str:
        """生成占用键（整改 S5-4：统一经 CacheKeyBuilder 模板，含 v1 版本段）"""
        return CacheKeyBuilder.build(CacheKeyBuilder.IDEMPOTENCY_OCCUPY, key=key)

    def _result_key(self, key: str) -> str:
        """生成结果键（整改 S5-4：统一经 CacheKeyBuilder 模板，含 v1 版本段）"""
        return CacheKeyBuilder.build(CacheKeyBuilder.IDEMPOTENCY_RESULT, key=key)

    async def try_occupy(self, key: str, ttl_seconds: int) -> bool:
        """SET NX 原子占用（跨实例唯一）"""
        return bool(await self._redis.set(self._occupy_key(key), "1", nx=True, ex=ttl_seconds))

    async def set_result(self, key: str, result: IdempotencyResult, ttl_seconds: int) -> None:
        """保存结果并清除占用标记"""
        result_key = self._result_key(key)
        await self._redis.set(
            result_key,
            json.dumps(
                {
                    "status_code": result.status_code,
                    "content_type": result.content_type,
                    "body": result.body.hex(),
                    "request_hash": result.request_hash,
                },
                ensure_ascii=False,
            ),
            ex=ttl_seconds,
        )
        await self._redis.delete(self._occupy_key(key))

    async def get_result(self, key: str) -> IdempotencyResult | None:
        """读取结果（未完成或已过期返回 None）"""
        raw = await self._redis.get(self._result_key(key))
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return IdempotencyResult(
                status_code=int(data["status_code"]),
                content_type=str(data["content_type"]),
                body=bytes.fromhex(str(data["body"])),
                request_hash=str(data["request_hash"]),
            )
        except (KeyError, ValueError, TypeError):
            return None

    async def release(self, key: str) -> None:
        """释放占用（业务处理异常时调用）"""
        await self._redis.delete(self._occupy_key(key))


def sha256_hex(value: str) -> str:
    """请求摘要：SHA-256 十六进制（规范 §5.6 摘要算法，禁 MD5）"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
