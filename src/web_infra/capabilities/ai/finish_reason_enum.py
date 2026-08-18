"""
生成结束原因枚举

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 生成结束原因枚举（AI 规范 §1.2）。
"""
from __future__ import annotations

from enum import Enum


class FinishReason(str, Enum):
    """生成结束原因（AI 规范 §1.2）；提供 get_code()/of(code)（规范 §5.2 入库存 code、未知码校验），description 返回中文描述"""

    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    TOOL_CALLS = "tool_calls"
    ERROR = "error"

    def get_code(self) -> int | str:
        """返回入库 code（规范 §5.2：入库存 code 禁存枚举名）"""
        return self.value

    @classmethod
    def of(cls, code: int | str) -> "FinishReason":
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
    "STOP": "正常结束（模型完成生成）",
    "LENGTH": "长度达到上限被截断",
    "CONTENT_FILTER": "内容过滤器触发中断",
    "TOOL_CALLS": "因工具调用而结束",
    "ERROR": "生成过程出错",
}
