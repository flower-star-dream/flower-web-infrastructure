"""
登录防爆破计数锁定服务

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 登录失败计数与账号/IP 双维度锁定（规范 §6.2 凭证安全、§25.1 应用层安全）。
              基于 Redis INCR 原子自增 + 首次失败设 TTL；计数达到阈值写入锁定 Key（TTL 即锁定时长）。
              Redis 不可用时降级为不计数、不锁定（保证可用性，与 backend 实现一致）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.exceptions import RedisError

from web_infra.infra.constants import CacheKeyBuilder
from web_infra.infra.logging import get_logger

logger = get_logger("security.login_fail_lock")


class LoginFailLockService:
    """登录失败计数锁定服务（账号 + IP 双维度）"""

    def __init__(
        self,
        redis: Any,
        max_user_fail_times: int = 5,
        max_ip_fail_times: int = 10,
        lock_ttl_seconds: int = 1800,
        fail_count_ttl_seconds: int = 1800,
    ) -> None:
        """初始化登录失败锁定服务。

        :param redis: redis.asyncio.Redis 兼容客户端（不可用时会降级）
        :param max_user_fail_times: 账号维度锁定阈值（默认 5 次）
        :param max_ip_fail_times: IP 维度锁定阈值（默认 10 次）
        :param lock_ttl_seconds: 锁定持续时间（秒，默认 30 分钟）
        :param fail_count_ttl_seconds: 失败计数保留时长（秒，默认 30 分钟）
        """
        self._redis = redis
        self.max_user_fail_times = max_user_fail_times
        self.max_ip_fail_times = max_ip_fail_times
        self.lock_ttl_seconds = lock_ttl_seconds
        self.fail_count_ttl_seconds = fail_count_ttl_seconds

    # ------------------------------------------------------------------
    # 内部：Key 构造
    # ------------------------------------------------------------------

    def _user_count_key(self, username: str) -> str:
        """账号失败计数 Key"""
        return CacheKeyBuilder.build(CacheKeyBuilder.LOGIN_FAIL_COUNT, username=username)

    def _user_lock_key(self, username: str) -> str:
        """账号锁定 Key"""
        return CacheKeyBuilder.build(CacheKeyBuilder.LOGIN_LOCK, username=username)

    def _ip_count_key(self, ip: str) -> str:
        """IP 失败计数 Key"""
        return CacheKeyBuilder.build(CacheKeyBuilder.LOGIN_IP_FAIL_COUNT, ip=ip)

    def _ip_lock_key(self, ip: str) -> str:
        """IP 锁定 Key"""
        return CacheKeyBuilder.build(CacheKeyBuilder.LOGIN_IP_LOCK, ip=ip)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    async def record_failure(self, username: str, ip: str) -> None:
        """记录一次登录失败：账号/IP 计数自增，达到阈值写入锁定 Key。

        Redis 异常时静默降级（不计数、不锁定）。
        """
        from redis.exceptions import RedisError

        try:
            user_count = await self._redis.incr(self._user_count_key(username))
            if user_count == 1:
                await self._redis.expire(self._user_count_key(username), self.fail_count_ttl_seconds)
            ip_count = await self._redis.incr(self._ip_count_key(ip))
            if ip_count == 1:
                await self._redis.expire(self._ip_count_key(ip), self.fail_count_ttl_seconds)

            if user_count >= self.max_user_fail_times:
                await self._redis.set(self._user_lock_key(username), "1", ex=self.lock_ttl_seconds)
            if ip_count >= self.max_ip_fail_times:
                await self._redis.set(self._ip_lock_key(ip), "1", ex=self.lock_ttl_seconds)
        except RedisError as e:
            logger.warning("login_fail_lock_degraded error=%s", str(e))

    async def is_locked(self, username: str, ip: str) -> bool:
        """判断账号或 IP 是否处于锁定状态。

        Redis 异常时返回 False（降级为不锁定，保证可用性）。
        """
        from redis.exceptions import RedisError

        try:
            user_locked = await self._redis.exists(self._user_lock_key(username))
            if user_locked:
                return True
            ip_locked = await self._redis.exists(self._ip_lock_key(ip))
            return bool(ip_locked)
        except RedisError as e:
            logger.warning("login_lock_check_degraded error=%s", str(e))
            return False

    async def clear(self, username: str, ip: str) -> None:
        """登录成功后清除账号与 IP 的失败计数与锁定状态。

        Redis 异常时静默降级。
        """
        from redis.exceptions import RedisError

        try:
            await self._redis.delete(
                self._user_count_key(username),
                self._user_lock_key(username),
                self._ip_count_key(ip),
                self._ip_lock_key(ip),
            )
        except RedisError as e:
            logger.warning("login_fail_lock_clear_degraded error=%s", str(e))
