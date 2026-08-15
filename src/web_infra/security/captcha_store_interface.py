"""
验证码存储接口

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 验证码存储抽象（SPI）：一次性消费语义由 take() 保证（取走即删除），
              支持内存（默认）与 Redis 实现，遵循规范 §25 应用层安全。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class CaptchaStoreInterface(ABC):
    """验证码存储接口"""

    @abstractmethod
    async def save(self, captcha_id: str, code: str, ttl_seconds: int) -> None:
        """保存验证码（含有效期）"""
        raise NotImplementedError

    @abstractmethod
    async def take(self, captcha_id: str) -> str | None:
        """取走验证码（一次性消费：成功取走后即删除，未命中/过期返回 None）"""
        raise NotImplementedError
