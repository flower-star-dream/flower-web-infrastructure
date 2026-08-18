"""
Demo 三方平台（模拟实现）

@Author: 花海
@Date: 2026/08/16 14:00
@Description: SocialPlatform 默认实现（不触网）：用于测试、演示与未接入真实平台时回落。
              授权码以 demo- 开头有效，token 与 openid 由授权码派生。
"""
from __future__ import annotations

from web_infra.infra.error import CommonErrorCode
from web_infra.capabilities.security.social.social_platform_interface import SocialAccessToken
from web_infra.capabilities.security.social.social_user_info import SocialUserInfo


class DemoSocialPlatform:
    """模拟三方平台（默认实现）"""

    provider = "demo"

    async def build_authorize_url(self, state: str, redirect_uri: str) -> str:
        """返回 redirect_uri?code=demo-{state}，模拟平台授权跳转回跳"""
        return f"{redirect_uri}?code=demo-{state}"

    async def exchange_token(self, code: str, redirect_uri: str) -> SocialAccessToken:
        """code 以 demo- 开头返回固定 token，否则抛 E2-AUTH-006"""
        if not code.startswith("demo-"):
            raise CommonErrorCode.AUTH_SOCIAL_TOKEN_FAILED.to_exception(message="Demo 平台授权码无效")
        return SocialAccessToken(
            access_token=f"demo-token-{code}",
            expires_in=600,
            openid=f"demo-openid-{code}",
            raw={"code": code},
        )

    async def fetch_userinfo(self, token: SocialAccessToken) -> SocialUserInfo:
        """返回 openid 由 token 派生的固定 userinfo"""
        openid = token.openid or "demo-openid"
        return SocialUserInfo(provider=self.provider, openid=openid, nickname=f"demo-user-{openid}", raw=token.raw)
