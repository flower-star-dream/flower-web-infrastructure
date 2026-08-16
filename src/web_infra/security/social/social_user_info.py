"""
三方用户信息统一结构

@Author: 花海
@Date: 2026/08/16 14:00
@Description: 三方平台用户信息统一载体（openid 为绑定唯一键一部分；raw 保留平台原始响应供业务扩展）。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SocialUserInfo:
    """三方平台用户信息"""

    provider: str
    openid: str  # 平台内唯一用户标识（绑定唯一键的一部分）
    unionid: str | None = None  # 平台内跨应用统一标识（如微信 unionid，可选）
    nickname: str | None = None
    avatar_url: str | None = None
    raw: dict = field(default_factory=dict)  # 平台原始响应，供业务扩展字段
