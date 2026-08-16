"""
三方登录结果

@Author: 花海
@Date: 2026/08/16 14:00
@Description: SocialLoginService.login 统一返回结构：已绑定返回自有 JWT 与本地用户，
              未绑定返回待绑定信号（bound=False）由业务决定自动注册或引导绑定。
"""
from __future__ import annotations

from dataclasses import dataclass

from web_infra.security.social.social_user_info import SocialUserInfo


@dataclass(frozen=True)
class SocialLoginResult:
    """三方登录结果"""

    access_token: str | None  # 已绑定登录时签发的框架自有 JWT；未绑定为 None
    user_id: str | None  # 本地用户 ID；未绑定为 None
    user_info: SocialUserInfo | None  # 三方用户信息（未绑定场景业务据此建号/引导）
    bound: bool  # 是否已完成绑定登录
