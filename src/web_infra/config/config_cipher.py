"""
配置加密/解密组件

@Author: 花海
@Date: 2026/08/15
@Description: 敏感配置加密存储组件（规范 §15.2 敏感配置走配置中心 + 加密存储，整改 S15-2）。
              约定格式：`enc:base64密文`（Fernet 对称加密，cryptography 库）。
              密钥通过环境变量 CONFIG_ENCRYPT_KEY / 构造参数注入，禁止落盘到代码或配置文件；
              密钥缺失时降级：仅解密失败返回原样（不抛错，避免启动失败），加密则明确报错。
"""
from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

# 加密值前缀约定（配置值为该前缀时按密文处理，否则视为明文原样返回）
ENCRYPTED_PREFIX = "enc:"
# 加密密钥环境变量名（规范 §15.2：密钥走环境变量/配置中心注入，禁止落盘）
ENV_ENCRYPT_KEY = "CONFIG_ENCRYPT_KEY"

logger = logging.getLogger(__name__)


class ConfigCipher:
    """配置加密/解密组件（Fernet 对称加密，规范 §15.2）"""

    def __init__(self, key: str | None = None) -> None:
        """初始化加密组件。

        :param key: Fernet 密钥（url-safe base64 编码的 32 字节），缺省从环境变量 CONFIG_ENCRYPT_KEY 读取；
                    未配置或密钥非法时告警并降级（decrypt 对 enc: 值返回原样，encrypt 抛错）
        """
        raw_key = key or os.getenv(ENV_ENCRYPT_KEY) or ""
        if not raw_key:
            logger.warning("未配置加密密钥（环境变量 %s），敏感配置仅解密失败返回原样（降级模式，规范 §15.2）", ENV_ENCRYPT_KEY)
            self._fernet: Fernet | None = None
            return
        try:
            self._fernet = Fernet(raw_key.encode("utf-8"))
        except (ValueError, TypeError):
            logger.warning("加密密钥格式非法（需 Fernet 密钥），敏感配置降级为原样返回（规范 §15.2）")
            self._fernet = None

    def encrypt(self, plain: str) -> str:
        """加密明文，返回 `enc:base64密文`（规范 §15.2 加密存储格式）。

        :param plain: 明文配置值
        :return: 带 enc: 前缀的密文
        :raises ValueError: 未配置加密密钥（防止无密钥时产生无法解密的伪密文）
        """
        if self._fernet is None:
            raise ValueError(f"未配置加密密钥（环境变量 {ENV_ENCRYPT_KEY}），无法加密敏感配置值")
        token = self._fernet.encrypt(plain.encode("utf-8"))
        return ENCRYPTED_PREFIX + token.decode("utf-8")

    def decrypt(self, value: str) -> str:
        """解密配置值：仅处理 `enc:` 前缀密文，其余原样返回。

        密钥缺失或解密失败（密钥错误/密文损坏）时告警并原样返回，不抛错——避免配置加载导致启动失败（规范 §15.2）。

        :param value: 配置值（可能为 enc: 前缀密文或明文）
        :return: 解密后的明文；非加密值/解密失败时为原值
        """
        if not value or not value.startswith(ENCRYPTED_PREFIX):
            return value
        if self._fernet is None:
            logger.warning("未配置加密密钥，无法解密 %s 前缀配置值，原样返回（规范 §15.2 降级）", ENCRYPTED_PREFIX)
            return value
        try:
            raw = value[len(ENCRYPTED_PREFIX):]
            return self._fernet.decrypt(raw.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeError):
            # InvalidToken：密文损坏/密钥不匹配；ValueError：base64 非法；UnicodeError：非 UTF-8 密文
            logger.warning("解密配置值失败（密钥不匹配或密文损坏），原样返回（规范 §15.2 降级）")
            return value
