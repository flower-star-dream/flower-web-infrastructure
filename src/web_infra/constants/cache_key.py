"""
缓存 Key 常量模板与统一生成器

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 缓存 Key 常量模板 + 统一生成方法，遵循规范 §5.6 / §5.7。
              模板统一按 INFRA_CACHE_KEY_PATTERN（web:{module}:v1:{biz}，见 infra_constant.py §5.7）
              组织：含版本号 v1，动态段运行时注入，业务禁止手写拼接（整改 S5-4，2026-08-15）。
              整改 S5-3：补充幂等域模板（API 幂等 §12.6 / 消息幂等 §9.2），
              原手写拼接 `前缀+key` 的存储统一改走本类生成。
"""
from __future__ import annotations

from typing import Any


class CacheKeyBuilder:
    """缓存 Key 统一生成器（规范 §5.6 / §5.7）"""

    # 认证域
    AUTH_TOKEN = "web:auth:v1:token:{user_id}:{jti}"
    AUTH_USER_TOKENS = "web:auth:v1:user_tokens:{user_id}"
    AUTH_DEVICE_TOKEN = "web:auth:v1:device_token:{user_id}:{client_id}:{device_id}"
    LOGIN_FAIL_COUNT = "web:auth:v1:login_fail_count:{username}"
    LOGIN_LOCK = "web:auth:v1:login_lock:{username}"
    LOGIN_IP_FAIL_COUNT = "web:auth:v1:login_fail_count_ip:{ip}"
    LOGIN_IP_LOCK = "web:auth:v1:login_lock_ip:{ip}"
    # 公共域：分布式锁 / 验证码 / 模型配置缓存
    DISTRIBUTED_LOCK = "web:common:v1:lock:{key}"
    CAPTCHA = "web:common:v1:captcha:{captcha_id}"
    MODEL_CONFIG = "web:common:v1:model_config:{code}"
    # 幂等域（整改 S5-4）：API 幂等占用/结果（规范 §12.6，{key} 为「用户 + 幂等键」联合业务键）、
    # 消息消费幂等（规范 §9.2，{key} 为「Topic + MsgId」联合业务键）
    IDEMPOTENCY_OCCUPY = "web:idem:v1:occupy:{key}"
    IDEMPOTENCY_RESULT = "web:idem:v1:result:{key}"
    MESSAGE_IDEMPOTENCY = "web:mq:v1:msg_idem:{key}"

    AUTH_TOKEN_TTL_SECONDS = 7200
    LOGIN_FAIL_TTL_SECONDS = 1800
    LOGIN_LOCK_TTL_SECONDS = 1800
    MODEL_CONFIG_TTL_SECONDS = 300

    @classmethod
    def build(cls, template: str, **kwargs: Any) -> str:
        """按模板注入动态段生成缓存 Key；动态段为空抛 ValueError"""
        for key, value in kwargs.items():
            if value is None or not str(value).strip():
                raise ValueError(f"缓存 Key 动态段 {key} 不能为空")
        return template.format(**kwargs)

    @classmethod
    def idempotency(cls, user_id: str, idem_key: str, *, occupy: bool = False) -> str:
        """生成 API 幂等键 Redis Key（规范 §12.6：userId + Idempotency-Key 联合唯一）。

        返回 web:idem:v1:{occupy|result}:{user_id}:{idem_key}（符合 §5.7 web:{module}:v1:{biz} 模板）。
        RedisIdempotencyStore 内部亦复用同一模板统一生成，禁止存储层手写拼接（整改 S5-4）。

        :param user_id: 用户标识（幂等作用域隔离）
        :param idem_key: 客户端幂等键（Idempotency-Key）
        :param occupy: True 生成占用键，False 生成结果键
        """
        template = cls.IDEMPOTENCY_OCCUPY if occupy else cls.IDEMPOTENCY_RESULT
        return cls.build(template, key=f"{user_id}:{idem_key}")

    @classmethod
    def message_idempotency(cls, topic: str, message_id: str) -> str:
        """生成消息消费幂等键 Redis Key（规范 §9.2：Topic + MsgId 联合幂等）。

        返回 web:mq:v1:msg_idem:{topic}:{message_id}（符合 §5.7 web:{module}:v1:{biz} 模板）。
        RedisMessageIdempotencyStore 内部亦复用同一模板统一生成，禁止存储层手写拼接（整改 S5-4）。
        """
        return cls.build(cls.MESSAGE_IDEMPOTENCY, key=f"{topic}:{message_id}")
