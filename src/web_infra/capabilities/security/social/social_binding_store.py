"""
三方账号绑定存储接口

@Author: 花海
@Date: 2026/08/16 14:00
@Description: 三方账号 ↔ 本地用户绑定记录与存储 SPI（唯一键 provider + openid，一用户可绑多平台多账号）。
              默认实现 InMemorySocialBindingStore；多实例需扩展 Redis/DB 实现。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SocialBinding:
    """三方账号 ↔ 本地用户绑定记录（唯一键 provider + openid）"""

    provider: str
    openid: str
    user_id: str
    bound_at: datetime


@runtime_checkable
class SocialBindingStore(Protocol):
    """三方账号绑定存储接口"""

    async def find_by_platform(self, provider: str, openid: str) -> SocialBinding | None:
        """按平台 + openid 查绑定；未绑定返回 None"""
        ...

    async def find_all_by_user_id(self, user_id: str) -> list[SocialBinding]:
        """查用户全部三方绑定"""
        ...

    async def bind(self, binding: SocialBinding) -> None:
        """绑定（provider+openid 唯一，已存在抛 COMMON_CONFLICT）"""
        ...

    async def unbind(self, provider: str, openid: str) -> bool:
        """解绑，返回是否实际删除"""
        ...
