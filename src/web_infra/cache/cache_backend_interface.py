"""
缓存后端接口

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 缓存后端统一抽象接口（异步），遵循规范 §8（缓存全生命周期）与 §16.5。
              抽象接口屏蔽本地缓存/Redis/配置中心缓存差异，防止技术栈锁定。
              提供空值占位（规范 §8.2 防缓存穿透）与 TTL 抖动（规范 §8.3 防缓存雪崩）能力：
              - set_empty/is_empty：标记"数据不存在"的空值占位，TTL 上限 EMPTY_TTL_LIMIT_SECONDS（120s）；
              - set 的 ttl_jitter_seconds 参数：ttl 生效时叠加 [0, ttl_jitter_seconds) 随机抖动。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# 空值占位 TTL 上限（秒，规范 §8.2：空值缓存 TTL ≤ 120s，防恶意高频请求直打 DB）
EMPTY_TTL_LIMIT_SECONDS = 120


@runtime_checkable
class CacheBackendInterface(Protocol):
    """缓存后端统一抽象接口（异步）"""

    async def get(self, key: str) -> Any | None:
        """读取缓存，未命中返回 None"""
        ...

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        ttl_jitter_seconds: float | None = None,
    ) -> None:
        """写入缓存。

        :param key: 缓存 Key
        :param value: 缓存值
        :param ttl: 过期秒数（None 使用后端默认 TTL）
        :param ttl_jitter_seconds: TTL 抖动上限（秒，None 使用后端默认配置，0 关闭；规范 §8.3 防雪崩）
        """
        ...

    async def delete(self, key: str) -> None:
        """删除缓存"""
        ...

    async def exists(self, key: str) -> bool:
        """判断缓存是否存在"""
        ...

    async def set_empty(self, key: str, ttl: int = 60) -> None:
        """写入空值占位（数据不存在标记，规范 §8.2 防缓存穿透）。

        :param key: 缓存 Key
        :param ttl: 空值占位过期秒数（默认 60，上限 EMPTY_TTL_LIMIT_SECONDS=120，超限自动钳制）
        """
        ...

    async def is_empty(self, key: str) -> bool:
        """判断是否处于空值占位状态（TTL 过期后自动失效返回 False）"""
        ...
