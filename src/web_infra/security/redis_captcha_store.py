"""
Redis 验证码存储

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 基于 Redis GETDEL 的验证码存储（多实例部署推荐），
              GETDEL 原子取走保证一次性消费，过期由 Redis TTL 兜底。
"""
from __future__ import annotations

from typing import Any

from web_infra.constants import CacheKeyBuilder
from web_infra.security.captcha_store_interface import CaptchaStoreInterface


class RedisCaptchaStore(CaptchaStoreInterface):
    """Redis 验证码存储（多实例部署推荐）"""

    def __init__(self, redis: Any) -> None:
        """初始化。

        :param redis: redis.asyncio.Redis 兼容客户端
        """
        self._redis = redis

    def _key(self, captcha_id: str) -> str:
        """拼接完整缓存 Key（带版本与业务域前缀，规范 §5.7）"""
        return CacheKeyBuilder.build(CacheKeyBuilder.CAPTCHA, captcha_id=captcha_id)

    async def save(self, captcha_id: str, code: str, ttl_seconds: int) -> None:
        await self._redis.set(self._key(captcha_id), code, ex=ttl_seconds)

    async def take(self, captcha_id: str) -> str | None:
        return await self._redis.getdel(self._key(captcha_id))
