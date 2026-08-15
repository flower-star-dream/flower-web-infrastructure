"""
图形验证码服务

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 验证码生成与校验（规范 §25 应用层安全：防机器人/暴力重放）。
              生成去混淆字符集验证码（去除 0/O/1/l/I 等易混淆字符），
              校验为一次性消费（取走即删除），TTL 过期自动失效。
              图片绘制不属于框架职责，调用方基于返回的 code 自行渲染。
"""
from __future__ import annotations

import random
import secrets
import string

from web_infra.security.captcha_store_interface import CaptchaStoreInterface
from web_infra.security.in_memory_captcha_store import InMemoryCaptchaStore

# 去混淆字符池：去除 0/O/1/l/I 等易混淆字符
_DEFAULT_CHAR_POOL = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class CaptchaService:
    """验证码生成与校验服务"""

    def __init__(self, store: CaptchaStoreInterface | None = None) -> None:
        """初始化验证码服务。

        :param store: 验证码存储（默认内存实现，多实例部署传入 RedisCaptchaStore）
        """
        self._store = store or InMemoryCaptchaStore()

    @property
    def store(self) -> CaptchaStoreInterface:
        """当前使用的验证码存储实现"""
        return self._store

    async def generate(self, ttl_seconds: int = 300, length: int = 4, char_pool: str = _DEFAULT_CHAR_POOL) -> tuple[str, str]:
        """生成验证码。

        :param ttl_seconds: 有效期（秒），默认 300
        :param length: 验证码长度，默认 4
        :param char_pool: 字符池，默认去混淆字符池
        :return: (captcha_id, 验证码)
        """
        captcha_id = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(16))
        code = "".join(random.choices(char_pool, k=length))
        await self._store.save(captcha_id, code, ttl_seconds)
        return captcha_id, code

    async def verify(self, captcha_id: str, code: str) -> bool:
        """校验验证码（一次性消费，大小写不敏感）。

        :param captcha_id: 验证码 ID
        :param code: 用户输入的验证码
        :return: 是否校验通过
        """
        if not captcha_id or not code:
            return False
        stored = await self._store.take(captcha_id)
        if stored is None:
            return False
        return stored.upper() == code.upper()
