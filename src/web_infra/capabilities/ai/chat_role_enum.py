"""
消息角色枚举

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一消息角色枚举，屏蔽供应商差异（AI 规范 §2.2）。
"""
from __future__ import annotations

from enum import Enum


class ChatRole(str, Enum):
    """消息角色；提供 get_code()/of(code)（规范 §5.2 入库存 code、未知码校验），description 返回中文描述"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

    def get_code(self) -> int | str:
        """返回入库 code（规范 §5.2：入库存 code 禁存枚举名）"""
        return self.value

    @classmethod
    def of(cls, code: int | str) -> "ChatRole":
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
    "SYSTEM": "系统消息",
    "USER": "用户消息",
    "ASSISTANT": "助手消息",
    "TOOL": "工具消息",
}
