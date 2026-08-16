"""
Redis JWT Token 状态存储

@Author: 花海
@Date: 2026/08/16 14:00
@Description: JwtTokenStore Redis 实现（多实例共享存储，框架启用 Redis 时的默认实现）：抽取原
              JWTUtil 的 Redis 状态逻辑（setex/sadd/expire 写状态与集合、delete/srem 撤销），
              Key 统一经 CacheKeyBuilder 生成（规范 §5.7 web:{module}:v1:{biz}，禁止手写拼接）。
              支持两种连接来源：直接注入 redis 客户端，或注入 RedisConfig 懒连接（跟随框架缓存 Redis）。
"""
from __future__ import annotations

from typing import Any

from web_infra.constants.cache_key import CacheKeyBuilder
from web_infra.db.redis_config import RedisConfig


class RedisJwtTokenStore:
    """Redis JWT Token 状态存储（分布式实现）"""

    def __init__(self, redis: Any | None = None, config: RedisConfig | None = None) -> None:
        """初始化。

        :param redis: redis 异步客户端（优先；需支持 get/setex/sadd/srem/expire/delete）
        :param config: Redis 连接配置（redis 未传时经 config.connect() 懒连接；框架启用 Redis 时默认装配）
        """
        if redis is None and config is None:
            raise ValueError("RedisJwtTokenStore 至少需注入 redis 客户端或 RedisConfig")
        self._redis = redis
        self._config = config

    async def _client(self) -> Any:
        """获取 redis 客户端：优先注入实例，否则经 RedisConfig 懒连接（连接失败抛 RedisError）"""
        if self._redis is None and self._config is not None:
            self._redis = await self._config.connect()
        return self._redis

    def _token_key(self, user_id: str, jti: str) -> str:
        """单凭证状态 Key"""
        return CacheKeyBuilder.build(CacheKeyBuilder.AUTH_TOKEN, user_id=user_id, jti=jti)

    def _user_tokens_key(self, user_id: str) -> str:
        """用户 token 集合 Key"""
        return CacheKeyBuilder.build(CacheKeyBuilder.AUTH_USER_TOKENS, user_id=user_id)

    def _device_key(self, user_id: str, client_id: str | None, device_id: str | None) -> str:
        """同设备复合键 Key（未传 client/device 用 none 占位，保证模板动态段非空）"""
        return CacheKeyBuilder.build(
            CacheKeyBuilder.AUTH_DEVICE_TOKEN,
            user_id=user_id,
            client_id=client_id or "none",
            device_id=device_id or "none",
        )

    async def save(self, user_id: str, jti: str, ttl_seconds: int,
                   client_id: str | None, device_id: str | None) -> str | None:
        """保存有效凭证；返回被同设备复用替换的旧 jti（无则 None）"""
        client = await self._client()
        device_key = self._device_key(user_id, client_id, device_id)
        old_jti = await client.get(device_key)
        if old_jti and old_jti != jti:
            old_jti = old_jti.decode() if isinstance(old_jti, bytes) else old_jti
            await client.delete(self._token_key(user_id, old_jti))
            await client.srem(self._user_tokens_key(user_id), old_jti)
        else:
            old_jti = None
        await client.setex(self._token_key(user_id, jti), ttl_seconds, "1")
        await client.sadd(self._user_tokens_key(user_id), jti)
        await client.expire(self._user_tokens_key(user_id), ttl_seconds)
        await client.setex(device_key, ttl_seconds, jti)
        return old_jti

    async def exists(self, user_id: str, jti: str) -> bool:
        """查询凭证是否有效"""
        client = await self._client()
        return bool(await client.get(self._token_key(user_id, jti)))

    async def revoke(self, user_id: str, jti: str) -> bool:
        """撤销凭证：删除状态 + 移出用户集合"""
        client = await self._client()
        deleted = await client.delete(self._token_key(user_id, jti))
        await client.srem(self._user_tokens_key(user_id), jti)
        return bool(deleted)

    async def current_jti(self, user_id: str, client_id: str | None, device_id: str | None) -> str | None:
        """查询同设备当前有效 jti"""
        client = await self._client()
        value = await client.get(self._device_key(user_id, client_id, device_id))
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)
