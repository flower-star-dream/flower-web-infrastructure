"""
三方登录模块

@Author: 花海
@Date: 2026/08/16 14:00
@Description: 导出三方登录 SPI 能力：平台适配接口与注册表、绑定存储接口、默认实现
              （Demo 平台 / 内存绑定存储）、SocialLoginService 编排。
"""
from web_infra.security.social.social_platform_interface import SocialPlatform, SocialAccessToken
from web_infra.security.social.social_user_info import SocialUserInfo
from web_infra.security.social.social_binding_store import SocialBinding, SocialBindingStore
from web_infra.security.social.social_platform_registry import SocialPlatformRegistry
from web_infra.security.social.in_memory_social_binding_store import InMemorySocialBindingStore
from web_infra.security.social.demo_social_platform import DemoSocialPlatform
from web_infra.security.social.social_login_result import SocialLoginResult
from web_infra.security.social.social_login_service import SocialLoginService

__all__ = [
    "SocialPlatform",
    "SocialAccessToken",
    "SocialUserInfo",
    "SocialBinding",
    "SocialBindingStore",
    "SocialPlatformRegistry",
    "InMemorySocialBindingStore",
    "DemoSocialPlatform",
    "SocialLoginResult",
    "SocialLoginService",
]
