"""
JWT 签名密钥/算法接口

@Author: 花海
@Date: 2026/08/16 14:00
@Description: JWT 签名密钥与算法 SPI（规范 §6.1 单独密钥段防混用、S15-3 密钥轮换）：
              默认 EnvJwtKeyProvider（环境变量密钥 + HS256）；开发者可替换为 RS256/KMS 托管等。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class JwtKeyProvider(Protocol):
    """JWT 签名密钥与算法"""

    def access_secret(self) -> str:
        """access token 签名密钥"""
        ...

    def refresh_secret(self) -> str:
        """refresh token 签名密钥（规范 §6.1 单独密钥段，与 access 双向防混用）"""
        ...

    def algorithm(self) -> str:
        """签名算法（如 HS256/RS256）"""
        ...
