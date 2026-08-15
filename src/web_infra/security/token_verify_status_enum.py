"""
Token 校验状态枚举

@Author: 花海
@Date: 2026/08/14 10:00
@Description: Token 校验状态：区分过期/非法/已登出/即将过期（触发静默刷新）。
"""

from __future__ import annotations

from enum import Enum


class TokenVerifyStatus(Enum):
    """Token 校验状态：区分过期/非法/已登出/即将过期；提供 get_code()/of(code)（规范 §5.2 入库存 code、未知码校验），description 返回中文描述"""

    VALID = "valid"
    EXPIRED = "expired"
    INVALID = "invalid"
    REVOKED = "revoked"
    # 凭证即将过期（规范 §6.1 静默刷新：剩余有效期低于阈值时返回本状态，触发 refresh token 静默续期，
    # 而非直接拒绝请求；由统一入口拦截识别后放行并异步刷新）
    EXPIRING = "expiring"

    def get_code(self) -> int | str:
        """返回入库 code（规范 §5.2：入库存 code 禁存枚举名）"""
        return self.value

    @classmethod
    def of(cls, code: int | str) -> "TokenVerifyStatus":
        """按 code 反查成员；未知 code 抛 ValueError（含枚举类名与收到的 code）"""
        for member in cls:
            if member.value == code:
                return member
        raise ValueError(f"未知的 {cls.__name__} code: {code!r}")

    @property
    def description(self) -> str:
        """返回中文描述（未收录成员返回空字符串）"""
        return _DESCRIPTIONS.get(self.name, "")


# 成员中文描述表（key=成员名，供 description 属性查询；未收录成员返回空字符串）
_DESCRIPTIONS: dict[str, str] = {
    "VALID": "校验通过",
    "EXPIRED": "已过期",
    "INVALID": "非法令牌",
    "REVOKED": "已登出（吊销）",
    "EXPIRING": "凭证即将过期",
}
