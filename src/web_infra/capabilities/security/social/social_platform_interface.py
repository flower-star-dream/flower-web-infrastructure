"""
三方平台适配接口

@Author: 花海
@Date: 2026/08/16 14:00
@Description: 三方登录平台适配 SPI（规范 §6.8 认证域）：授权跳转 URL 生成、授权码换 token、
              拉取三方用户信息。业务实现具体平台（微信/GitHub/钉钉...）后注册进 SocialPlatformRegistry。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from web_infra.capabilities.security.social.social_user_info import SocialUserInfo


@dataclass(frozen=True)
class SocialAccessToken:
    """平台 access token（授权码换取结果）"""

    access_token: str
    expires_in: int
    openid: str | None = None
    raw: dict = field(default_factory=dict)


@runtime_checkable
class SocialPlatform(Protocol):
    """三方平台适配接口"""

    provider: str  # 平台标识（注册表键），如 wechat_open / github / demo

    async def build_authorize_url(self, state: str, redirect_uri: str) -> str:
        """生成授权跳转 URL（state 由调用方生成用于防 CSRF）"""
        ...

    async def exchange_token(self, code: str, redirect_uri: str) -> SocialAccessToken:
        """授权码换取平台 token"""
        ...

    async def fetch_userinfo(self, token: SocialAccessToken) -> SocialUserInfo:
        """拉取三方用户信息（入参为换取的 token，内含 access_token/openid/raw，
        供微信等需要 openid 的接口使用）"""
        ...
