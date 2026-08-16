"""
JWT 环境变量密钥提供器

@Author: 花海
@Date: 2026/08/16 14:00
@Description: JwtKeyProvider 默认实现：密钥来自环境变量（SecureConfigLoader，规范 §15.2），
              算法固定 HS256；refresh 密钥为主密钥派生独立段（规范 §6.1 防混用）。
"""
from __future__ import annotations

from web_infra.constants.auth_constant import AuthConstant
from web_infra.security.secure_config_loader import SecureConfigLoader


class EnvJwtKeyProvider:
    """环境变量密钥 + HS256（JwtKeyProvider 默认实现）"""

    def access_secret(self) -> str:
        """access token 签名密钥（环境变量 JWT_SECRET_KEY，规范 §15.2 禁止落盘）"""
        return SecureConfigLoader.get_jwt_secret()

    def refresh_secret(self) -> str:
        """refresh token 单独密钥段（规范 §6.1：主密钥派生 + :refresh 后缀，与 access 双向防混用）"""
        return SecureConfigLoader.get_jwt_secret() + ":refresh"

    def algorithm(self) -> str:
        """签名算法"""
        return AuthConstant.AUTH_JWT_ALGORITHM
