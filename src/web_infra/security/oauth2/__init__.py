"""
OAuth2 最小实现模块

@Author: 花海
@Date: 2026/08/14 20:00
@Description: 导出 OAuth2 最小令牌签发校验能力（规范 §6.1/§6.2/§6.4/§6.7）：
              客户端注册 SPI（内存默认）与令牌服务（client_credentials 签发/校验/撤销）。
"""
from web_infra.security.oauth2.oauth2_client import OAuth2Client
from web_infra.security.oauth2.oauth2_client_registry import (
    OAuth2ClientRegistry,
    InMemoryOAuth2ClientRegistry,
)
from web_infra.security.oauth2.oauth2_token_service import OAuth2TokenService

__all__ = [
    "OAuth2Client",
    "OAuth2ClientRegistry",
    "InMemoryOAuth2ClientRegistry",
    "OAuth2TokenService",
]
