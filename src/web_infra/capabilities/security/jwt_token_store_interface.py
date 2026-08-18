"""
JWT Token 状态存储接口

@Author: 花海
@Date: 2026/08/16 14:00
@Description: JWT Token 状态存储 SPI（规范 §6.2 同设备凭证复用、§6.7 凭证撤销）：
              记录 jti 有效性、同设备复合键映射与用户 token 集合。
              默认实现 InMemoryJwtTokenStore（单实例）/ RedisJwtTokenStore（分布式）。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class JwtTokenStore(Protocol):
    """JWT Token 状态存储：jti 有效性（登出撤销）、同设备凭证复用"""

    async def save(self, user_id: str, jti: str, ttl_seconds: int,
                   client_id: str | None, device_id: str | None) -> str | None:
        """保存有效凭证：记录 (user_id, jti) 状态 + 用户 token 集合 + 同设备复合键映射；
        返回被替换的旧 jti（同设备复用语义，无则 None）"""
        ...

    async def exists(self, user_id: str, jti: str) -> bool:
        """查询凭证是否有效（撤销/过期/被复用替换后返回 False）"""
        ...

    async def revoke(self, user_id: str, jti: str) -> bool:
        """撤销凭证（登出）：删除状态 + 移出用户 token 集合，返回是否实际撤销"""
        ...

    async def current_jti(self, user_id: str, client_id: str | None, device_id: str | None) -> str | None:
        """查询同设备当前有效 jti（未记录返回 None）"""
        ...
