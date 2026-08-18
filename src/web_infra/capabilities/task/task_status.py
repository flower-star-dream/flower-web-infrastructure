"""
任务状态枚举

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 异步任务状态（规范 §9 异步化 / §23 任务执行记录），
              终态：SUCCESS / FAILED / DEAD / REJECTED，不可再流转。
"""
from __future__ import annotations

from enum import Enum


class TaskStatus(Enum):
    """异步任务状态；提供 get_code()/of(code)（规范 §5.2 入库存 code、未知码校验），description 返回中文描述"""

    PENDING = "PENDING"      # 已提交待执行
    RUNNING = "RUNNING"      # 执行中
    SUCCESS = "SUCCESS"      # 成功（终态）
    FAILED = "FAILED"        # 失败（终态）
    DEAD = "DEAD"            # 心跳超时判定死亡（终态）
    REJECTED = "REJECTED"    # 线程池拒绝（终态）
    SKIPPED = "SKIPPED"      # 调度跳过（锁竞争/任务暂停等，终态，整改 S23-1/S23-2）

    def get_code(self) -> int | str:
        """返回入库 code（规范 §5.2：入库存 code 禁存枚举名）"""
        return self.value

    @classmethod
    def of(cls, code: int | str) -> "TaskStatus":
        """按 code 反查成员；未知 code 抛 ValueError（含枚举类名与收到的 code）"""
        for member in cls:
            if member.value == code:
                return member
        raise ValueError(f"未知的 {cls.__name__} code: {code!r}")

    @property
    def description(self) -> str:
        """返回中文描述（未收录成员返回空字符串）"""
        return _DESCRIPTIONS.get(self.name, "")

    @property
    def is_terminal(self) -> bool:
        """是否终态（终态不可再流转）"""
        return self in (
            TaskStatus.SUCCESS,
            TaskStatus.FAILED,
            TaskStatus.DEAD,
            TaskStatus.REJECTED,
            TaskStatus.SKIPPED,
        )


# 成员中文描述表（key=成员名，供 description 属性查询；未收录成员返回空字符串）
_DESCRIPTIONS: dict[str, str] = {
    "PENDING": "已提交待执行",
    "RUNNING": "执行中",
    "SUCCESS": "成功（终态）",
    "FAILED": "失败（终态）",
    "DEAD": "心跳超时判定死亡（终态）",
    "REJECTED": "线程池拒绝（终态）",
    "SKIPPED": "调度跳过（终态）",
}
