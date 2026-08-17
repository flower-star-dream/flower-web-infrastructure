"""
内存 JWT Token 状态存储

@Author: 花海
@Date: 2026/08/16 14:00
@Description: JwtTokenStore 内存默认实现（单实例，等价原 JWTUtil._device_tokens + 状态记录）：
              进程内维护 jti 状态（带 TTL）、同设备复合键映射、用户 token 集合；
              惰性清理过期条目（M5 修复：防内存无界增长），RLock 保护复合读写原子性
              （M4 修复：跨线程并发 save/exists/revoke 不丢失状态）。
              多实例部署需替换为 RedisJwtTokenStore 等共享存储。
"""
from __future__ import annotations

import time
from threading import RLock
from typing import Any


class InMemoryJwtTokenStore:
    """内存 JWT Token 状态存储（单实例默认实现）

    @Stateful：进程内存储，单实例/单进程部署，多实例需替换为分布式实现（S1-1）。
    """

    def __init__(self) -> None:
        self._states: dict[str, tuple[str, float]] = {}  # "user_id:jti" -> (marker, expire_at)
        self._device_map: dict[tuple[str, str, str], str] = {}  # (user, client, device) -> jti
        self._user_jtis: dict[str, set[str]] = {}  # user_id -> {jti}
        # 线程锁：保护复合读写原子性（读改写一体，M4 修复）
        self._lock = RLock()

    def _key(self, user_id: str, jti: str) -> str:
        """状态键（user_id + jti 唯一标识一条凭证状态）"""
        return f"{user_id}:{jti}"

    def _composite(self, user_id: str, client_id: str | None, device_id: str | None) -> tuple[str, str, str]:
        """同设备复合键（未传 client/device 按空串聚合，与历史语义一致）"""
        return (user_id, client_id or "", device_id or "")

    async def save(self, user_id: str, jti: str, ttl_seconds: int,
                   client_id: str | None, device_id: str | None) -> str | None:
        """保存有效凭证；返回被同设备复用替换的旧 jti（无则 None）"""
        with self._lock:
            now = time.monotonic()
            # 惰性清理该用户已过期凭证（M5 修复：防 _states/_device_map/_user_jtis 无界增长）
            self._prune_user(user_id, now)
            composite = self._composite(user_id, client_id, device_id)
            old_jti = self._device_map.get(composite)
            if old_jti and old_jti != jti:
                self._states.pop(self._key(user_id, old_jti), None)
                user_set = self._user_jtis.get(user_id)
                if user_set:
                    user_set.discard(old_jti)
            self._device_map[composite] = jti
            self._states[self._key(user_id, jti)] = (jti, now + ttl_seconds)
            self._user_jtis.setdefault(user_id, set()).add(jti)
            return old_jti if old_jti != jti else None

    async def exists(self, user_id: str, jti: str) -> bool:
        """查询凭证是否有效（未记录/已撤销/已过期返回 False；过期条目同步清理，M5 修复）"""
        with self._lock:
            now = time.monotonic()
            item = self._states.get(self._key(user_id, jti))
            if item is None:
                return False
            _, expire_at = item
            if now < expire_at:
                return True
            self._states.pop(self._key(user_id, jti), None)
            self._discard_user_jti(user_id, jti)
            return False

    async def revoke(self, user_id: str, jti: str) -> bool:
        """撤销凭证：删除状态 + 移出用户集合"""
        with self._lock:
            if self._states.pop(self._key(user_id, jti), None) is None:
                return False
            self._discard_user_jti(user_id, jti)
            return True

    async def current_jti(self, user_id: str, client_id: str | None, device_id: str | None) -> str | None:
        """查询同设备当前有效 jti"""
        with self._lock:
            return self._device_map.get(self._composite(user_id, client_id, device_id))

    # ------------------------------------------------------------------
    # 内部：过期清理与集合维护（M5 修复）
    # ------------------------------------------------------------------

    def _prune_user(self, user_id: str, now: float) -> None:
        """惰性清理该用户已过期凭证，并同步清理 device_map 指向失效 jti 的条目"""
        user_set = self._user_jtis.get(user_id)
        if not user_set:
            return
        for jti in list(user_set):
            if self._states.get(self._key(user_id, jti), (None, 0))[1] <= now:
                self._states.pop(self._key(user_id, jti), None)
                user_set.discard(jti)
        if not user_set:
            self._user_jtis.pop(user_id, None)
            return
        # device_map 中指向已被移出集合（过期/替换）jti 的条目一并清理，防残留
        stale = [c for c, j in self._device_map.items() if c[0] == user_id and j not in user_set]
        for composite in stale:
            self._device_map.pop(composite, None)

    def _discard_user_jti(self, user_id: str, jti: str) -> None:
        """将 jti 移出用户集合（集合清空时回收 user_id 键，防残留）"""
        user_set = self._user_jtis.get(user_id)
        if not user_set:
            return
        user_set.discard(jti)
        if not user_set:
            self._user_jtis.pop(user_id, None)
