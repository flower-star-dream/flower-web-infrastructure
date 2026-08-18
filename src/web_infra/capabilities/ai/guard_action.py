"""
内容审核动作枚举

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 内容安全审核动作（AI 规范 §7.2）：阻断/警告/放行。
"""
from __future__ import annotations

from enum import Enum


class GuardAction(Enum):
    """内容审核动作；提供 get_code()/of(code)（规范 §5.2 入库存 code、未知码校验），description 返回中文描述"""

    BLOCK = "BLOCK"    # 阻断（输入禁止进入模型 / 输出禁止返回用户）
    WARN = "WARN"      # 警告（放行但附带警示）
    PASS = "PASS"      # 放行（未命中任何规则）

    def get_code(self) -> int | str:
        """返回入库 code（规范 §5.2：入库存 code 禁存枚举名）"""
        return self.value

    @classmethod
    def of(cls, code: int | str) -> "GuardAction":
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
    "BLOCK": "阻断（输入禁止进入模型 / 输出禁止返回用户）",
    "WARN": "警告（放行但附带警示）",
    "PASS": "放行（未命中任何规则）",
}
