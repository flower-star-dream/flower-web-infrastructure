"""
安全配置加载器

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一从环境变量读取安全密钥（JWT 等），禁止写入代码或配置文件，遵循规范 §15.2 配置安全。
              整改 S15-2（2026-08-15）：支持 `enc:base64密文` 加密配置值（Fernet，ConfigCipher），
              读取配置时自动解密；密钥走环境变量 CONFIG_ENCRYPT_KEY 注入，禁止落盘。
"""
from __future__ import annotations

import os

from web_infra.config.config_cipher import ConfigCipher


class SecureConfigLoader:
    """从环境变量加载安全密钥（支持 enc: 前缀加密值自动解密，规范 §15.2）"""

    @classmethod
    def _decrypt(cls, value: str) -> str:
        """解密 enc: 前缀配置值（规范 §15.2 敏感配置加密存储）；非加密值原样返回。

        内部延迟创建 ConfigCipher（密钥取环境变量 CONFIG_ENCRYPT_KEY）；
        密钥缺失/解密失败时由 ConfigCipher 降级为原样返回，不抛错（避免启动失败）。
        """
        if not value or not value.startswith("enc:"):
            return value
        return ConfigCipher().decrypt(value)

    @classmethod
    def _require(cls, key: str) -> str:
        """必须从环境变量读取，未设置则抛异常"""
        value = os.getenv(key)
        if not value:
            raise RuntimeError(f"安全密钥 {key} 未通过环境变量注入，禁止写入代码或配置文件")
        return cls._decrypt(value)

    @classmethod
    def _env_or_default(cls, key: str, default: str | None = None) -> str | None:
        """优先环境变量，未设置返回 default；配置值为 enc: 密文时自动解密（规范 §15.2）"""
        value = os.getenv(key)
        if not value:
            return default
        return cls._decrypt(value)

    @classmethod
    def get_jwt_secret(cls) -> str:
        """获取 JWT 签名密钥，必须来自环境变量（支持 enc: 前缀加密值）"""
        return cls._require("JWT_SECRET_KEY")

    @classmethod
    def get_jwt_expire_minutes(cls, default: int = 120) -> int:
        """获取 JWT 过期时间（分钟），默认 120"""
        value = cls._env_or_default("JWT_EXPIRE_MINUTES", str(default))
        try:
            return int(value or default)
        except ValueError:
            return default
