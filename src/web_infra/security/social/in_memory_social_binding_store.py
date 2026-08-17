"""
内存三方账号绑定存储

@Author: 花海
@Date: 2026/08/16 14:00
@Description: SocialBindingStore 内存默认实现（单实例，多实例需扩展 Redis/DB）：
              (provider, openid) -> SocialBinding；重复绑定抛 COMMON_CONFLICT。
              检查-写入原子性由 RLock 保护（M3 修复：并发绑定同一 openid 仅一个成功，
              其余抛 COMMON_CONFLICT，由服务层幂等容错兜底）。
"""
from __future__ import annotations

from threading import RLock

from web_infra.error import CommonErrorCode
from web_infra.security.social.social_binding_store import SocialBinding


class InMemorySocialBindingStore:
    """内存三方账号绑定存储（单实例默认实现）"""

    def __init__(self) -> None:
        self._bindings: dict[tuple[str, str], SocialBinding] = {}
        # 线程锁：保护 bind 的「检查-写入」原子性（M3 修复）
        self._lock = RLock()

    def _key(self, provider: str, openid: str) -> tuple[str, str]:
        """唯一键（provider + openid）"""
        return (provider, openid)

    async def find_by_platform(self, provider: str, openid: str) -> SocialBinding | None:
        """按平台 + openid 查绑定；未绑定返回 None"""
        with self._lock:
            return self._bindings.get(self._key(provider, openid))

    async def find_all_by_user_id(self, user_id: str) -> list[SocialBinding]:
        """查用户全部三方绑定"""
        with self._lock:
            return [b for b in self._bindings.values() if b.user_id == user_id]

    async def bind(self, binding: SocialBinding) -> None:
        """绑定（provider+openid 唯一，已存在抛 COMMON_CONFLICT；检查-写入原子）"""
        with self._lock:
            key = self._key(binding.provider, binding.openid)
            if key in self._bindings:
                raise CommonErrorCode.COMMON_CONFLICT.to_exception(
                    message=f"三方账号已绑定: {binding.provider}/{binding.openid}"
                )
            self._bindings[key] = binding

    async def unbind(self, provider: str, openid: str) -> bool:
        """解绑，返回是否实际删除"""
        with self._lock:
            return self._bindings.pop(self._key(provider, openid), None) is not None
