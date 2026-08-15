"""
密码加密

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 基于 bcrypt 的密码加密（类似 Spring Security BCryptPasswordEncoder），
              遵循规范 §15.2 配置安全。bcrypt 仅使用前 72 字节，超长密码截断。
"""
from __future__ import annotations

import bcrypt

from web_infra.constants.auth_constant import AuthConstant


class PasswordEncoder:
    """bcrypt 密码加密工具"""

    @staticmethod
    def _truncate(password: str) -> bytes:
        """截断密码为 UTF-8 前 72 字节"""
        return password.encode("utf-8")[: AuthConstant.AUTH_PASSWORD_BCRYPT_MAX_BYTES]

    @staticmethod
    def encode(password: str) -> str:
        """加密密码，返回 bcrypt 哈希"""
        return bcrypt.hashpw(PasswordEncoder._truncate(password), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify(plain_password: str, hashed_password: str) -> bool:
        """校验密码是否匹配"""
        return bcrypt.checkpw(PasswordEncoder._truncate(plain_password), hashed_password.encode("utf-8"))
