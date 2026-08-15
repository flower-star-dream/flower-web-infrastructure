"""
消息幂等键存储接口

@Author: 花海
@Date: 2026/08/14 19:00
@Description: 消息消费幂等键存储抽象接口（规范 §9.2：bizId + msgId 联合幂等，保留 7 天，
              Redis SETNX / DB 唯一约束保证跨实例原子性）。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MessageIdempotencyStoreInterface(Protocol):
    """消息消费幂等键存储抽象接口"""

    async def try_consume(self, key: str, ttl_seconds: int) -> bool:
        """尝试写入消费幂等键：首次写入成功返回 True；已存在（重复消费）返回 False（规范 §9.2）"""
        ...

    async def release(self, key: str) -> None:
        """回滚占用（业务处理失败时调用，允许重试，规范 §9.6）"""
        ...
