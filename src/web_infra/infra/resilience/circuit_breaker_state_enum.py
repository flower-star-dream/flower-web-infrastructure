"""
熔断器状态枚举

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 熔断器状态枚举，遵循规范 §7.4。
"""
from __future__ import annotations

from enum import Enum


class CircuitBreakerState(str, Enum):
    """熔断器状态；提供 get_code()/of(code)（规范 §5.2 入库存 code、未知码校验），description 返回中文描述"""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def get_code(self) -> int | str:
        """返回入库 code（规范 §5.2：入库存 code 禁存枚举名）"""
        return self.value

    @classmethod
    def of(cls, code: int | str) -> "CircuitBreakerState":
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
    "CLOSED": "关闭（正常放行）",
    "OPEN": "打开（熔断拒绝）",
    "HALF_OPEN": "半开（试探放行）",
}
