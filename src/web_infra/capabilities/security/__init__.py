"""
安全模块

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 安全能力聚合：JWT、密码加密、密钥加载、PII 脱敏、验证码、登录防爆破计数锁定。
"""
from web_infra.capabilities.security.jwt_util import JWTUtil
from web_infra.capabilities.security.token_verify_status_enum import TokenVerifyStatus
from web_infra.capabilities.security.password_encoder import PasswordEncoder
from web_infra.capabilities.security.secure_config_loader import SecureConfigLoader
from web_infra.capabilities.security.privacy_guard import PrivacyGuard
from web_infra.capabilities.security.pii_result import PiiResult
from web_infra.capabilities.security.pii_match import PiiMatch
from web_infra.capabilities.security.captcha_store_interface import CaptchaStoreInterface
from web_infra.capabilities.security.in_memory_captcha_store import InMemoryCaptchaStore
from web_infra.capabilities.security.redis_captcha_store import RedisCaptchaStore
from web_infra.capabilities.security.captcha_service import CaptchaService
from web_infra.capabilities.security.login_fail_lock import LoginFailLockService
from web_infra.capabilities.security.permission_guard import PermissionGuard
from web_infra.capabilities.security.oauth2 import (
    OAuth2Client,
    OAuth2ClientRegistry,
    InMemoryOAuth2ClientRegistry,
    OAuth2TokenService,
)
from web_infra.capabilities.security.jwt_token_store_interface import JwtTokenStore
from web_infra.capabilities.security.in_memory_jwt_token_store import InMemoryJwtTokenStore
from web_infra.capabilities.security.redis_jwt_token_store import RedisJwtTokenStore
from web_infra.capabilities.security.jwt_key_provider_interface import JwtKeyProvider
from web_infra.capabilities.security.env_jwt_key_provider import EnvJwtKeyProvider
from web_infra.capabilities.security.social import (
    SocialPlatform,
    SocialAccessToken,
    SocialUserInfo,
    SocialBinding,
    SocialBindingStore,
    InMemorySocialBindingStore,
    SocialPlatformRegistry,
    DemoSocialPlatform,
    SocialLoginResult,
    SocialLoginService,
)

__all__ = [
    "JWTUtil",
    "TokenVerifyStatus",
    "PasswordEncoder",
    "SecureConfigLoader",
    "PrivacyGuard",
    "PiiResult",
    "PiiMatch",
    "CaptchaStoreInterface",
    "InMemoryCaptchaStore",
    "RedisCaptchaStore",
    "CaptchaService",
    "LoginFailLockService",
    "PermissionGuard",
    "OAuth2Client",
    "OAuth2ClientRegistry",
    "InMemoryOAuth2ClientRegistry",
    "OAuth2TokenService",
    "JwtTokenStore", "InMemoryJwtTokenStore", "RedisJwtTokenStore",
    "JwtKeyProvider", "EnvJwtKeyProvider",
    "SocialPlatform", "SocialAccessToken", "SocialUserInfo", "SocialBinding",
    "SocialBindingStore", "InMemorySocialBindingStore", "SocialPlatformRegistry",
    "DemoSocialPlatform", "SocialLoginResult", "SocialLoginService",
]
