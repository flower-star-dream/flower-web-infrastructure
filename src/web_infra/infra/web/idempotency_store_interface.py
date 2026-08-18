"""
幂等键存储接口

@Author: 花海
@Date: 2026/08/14 18:30
@Description: API 幂等键存储抽象接口（规范 §12.6：幂等键 + 请求摘要 + 处理结果三要素存储，
              TTL 覆盖重试窗口如 24h；Redis/DB 保证原子性）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class IdempotencyResult:
    """幂等处理结果（重复请求直接返回，规范 §12.6 幂等键 + 结果缓存）"""

    status_code: int  # 首次处理的 HTTP 状态码
    content_type: str  # 响应 Content-Type
    body: bytes  # 响应体（原始字节）
    request_hash: str  # 首次请求摘要（重复请求校验一致性）


@runtime_checkable
class IdempotencyStoreInterface(Protocol):
    """幂等键存储抽象接口"""

    async def try_occupy(self, key: str, ttl_seconds: int) -> bool:
        """原子占用幂等键（SETNX 语义）：首次返回 True，重复占用返回 False（规范 §12.6 原子性）"""
        ...

    async def set_result(self, key: str, result: IdempotencyResult, ttl_seconds: int) -> None:
        """保存首次处理结果"""
        ...

    async def get_result(self, key: str) -> IdempotencyResult | None:
        """读取已缓存的处理结果（未完成或无结果返回 None）"""
        ...

    async def release(self, key: str) -> None:
        """释放占用（业务处理异常时调用，允许后续请求重试）"""
        ...
