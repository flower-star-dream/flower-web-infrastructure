"""
Outbox 消息状态枚举

@Author: 花海
@Date: 2026/08/14 19:00
@Description: Outbox 本地事务表消息状态（规范 §21.3 附录 A.13.4：
              0 待发送 / 1 已发送 / 2 失败超限 / 3 死信队列）。
"""
from __future__ import annotations

from enum import IntEnum


class OutboxStatus(IntEnum):
    """Outbox 消息状态；提供 get_code()/of(code)（规范 §5.2 入库存 code、未知码校验），description 返回中文描述"""

    PENDING = 0  # 待发送（本地事务已提交，待轮询投递）
    SENT = 1  # 已发送（Broker 确认投递成功）
    FAILED = 2  # 失败超限（重试次数超限，未投递死信时的兜底状态）
    DLQ = 3  # 死信（重试超限或不可重试，已投递到死信主题，规范 P0-3/S9-7）

    def get_code(self) -> int | str:
        """返回入库 code（规范 §5.2：入库存 code 禁存枚举名）"""
        return int(self.value)

    @classmethod
    def of(cls, code: int | str) -> "OutboxStatus":
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
    "PENDING": "待发送（本地事务已提交，待轮询投递）",
    "SENT": "已发送（Broker 确认投递成功）",
    "FAILED": "失败超限（重试次数超限，未投递死信时的兜底状态）",
    "DLQ": "死信（重试超限或不可重试，已投递到死信主题）",
}
