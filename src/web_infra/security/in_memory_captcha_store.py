"""
内存验证码存储

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 基于内存字典 + asyncio.Lock 的验证码存储（默认实现，单实例场景），
              带过期清理，take() 原子取走保证一次性消费。多实例部署需切换 RedisCaptchaStore。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from web_infra.security.captcha_store_interface import CaptchaStoreInterface


class InMemoryCaptchaStore(CaptchaStoreInterface):
    """内存验证码存储（单实例默认实现）

    @Stateful：进程内内存存储，单实例/单进程部署，多实例需替换为分布式实现（S1-1）。
    仅限单事件循环访问（asyncio.Lock 不跨线程互斥），跨线程/跨循环场景请改用线程安全或分布式实现。
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}  # captcha_id -> (code, expire_at)
        self._lock = asyncio.Lock()

    def _purge_expired_locked(self) -> None:
        """清理过期项（调用方必须持有 _lock）"""
        now = time.monotonic()
        expired = [cid for cid, (_, expire_at) in self._store.items() if expire_at <= now]
        for cid in expired:
            self._store.pop(cid, None)

    async def save(self, captcha_id: str, code: str, ttl_seconds: int) -> None:
        async with self._lock:
            self._store[captcha_id] = (code, time.monotonic() + ttl_seconds)
            self._purge_expired_locked()

    async def take(self, captcha_id: str) -> str | None:
        async with self._lock:
            item = self._store.get(captcha_id)
            if item is None:
                return None
            code, expire_at = item
            self._store.pop(captcha_id, None)  # 一次性消费：无论是否过期均取走
            if expire_at <= time.monotonic():
                return None
            return code
