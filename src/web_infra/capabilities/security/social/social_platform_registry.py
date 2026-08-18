"""
三方平台注册表

@Author: 花海
@Date: 2026/08/16 14:00
@Description: 三方平台显式注册表（规范 SPI：显式注册，扩展不散落）；未注册平台取用由
              SocialLoginService 抛 E2-AUTH-005。
"""
from __future__ import annotations

from web_infra.capabilities.security.social.social_platform_interface import SocialPlatform


class SocialPlatformRegistry:
    """三方平台注册表"""

    def __init__(self) -> None:
        self._platforms: dict[str, SocialPlatform] = {}

    def register(self, platform: SocialPlatform) -> None:
        """注册平台（provider 已存在时覆盖）"""
        self._platforms[platform.provider] = platform

    def get(self, provider: str) -> SocialPlatform | None:
        """按 provider 查平台；未注册返回 None"""
        return self._platforms.get(provider)

    def providers(self) -> list[str]:
        """列出全部已注册 provider"""
        return list(self._platforms.keys())
