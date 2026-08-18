"""
分片上传任务状态枚举

@Author: 花海
@Date: 2026/08/14 19:30
@Description: 分片上传任务状态（规范 §22.4：初始化上传任务 -> 逐片上传 -> 合并校验 -> 清理）。
"""
from __future__ import annotations

from enum import IntEnum


class UploadStatus(IntEnum):
    """分片上传任务状态；提供 get_code()/of(code)（规范 §5.2 入库存 code、未知码校验），description 返回中文描述"""

    INITIALIZED = 0  # 已初始化（待逐片上传）
    COMPLETED = 1  # 已合并完成（对象已落库）
    FAILED = 2  # 失败/取消（合并前中断）

    def get_code(self) -> int | str:
        """返回入库 code（规范 §5.2：入库存 code 禁存枚举名）"""
        return int(self.value)

    @classmethod
    def of(cls, code: int | str) -> "UploadStatus":
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
    "INITIALIZED": "已初始化（待逐片上传）",
    "COMPLETED": "已合并完成（对象已落库）",
    "FAILED": "失败/取消（合并前中断）",
}
