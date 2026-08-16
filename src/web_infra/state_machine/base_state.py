"""
状态枚举基类

@Author: 花海
@Date: 2026/08/16 16:00
@Description: 状态枚举基类（推荐便捷基类，非强制——引擎不要求状态必须继承本类），
              成员 value 即业务码（get_code()），
              description 返回中文名，of(code) 反查（未知码抛 UNKNOWN_STATE）。
"""
from __future__ import annotations

from enum import Enum

from web_infra.state_machine.state_machine_error import StateMachineErrorCode


class BaseState(Enum):
    """状态枚举基类：业务侧 `class OrderStatus(BaseState): PAID = (1, "已支付")` 声明"""

    def __new__(cls, code: int | str, description: str) -> "BaseState":
        obj = object.__new__(cls)
        obj._value_ = code
        obj._description_ = description
        return obj

    @property
    def description(self) -> str:
        """返回状态中文名"""
        return self._description_

    def get_code(self) -> int | str:
        """返回入库业务码（规范 §5.2：入库存 code 禁存枚举名）"""
        return self.value

    @classmethod
    def of(cls, code: int | str) -> "BaseState":
        """按业务码反查成员；未知码抛 UNKNOWN_STATE（E4-STATE-004）"""
        for member in cls:
            if member.value == code:
                return member
        raise StateMachineErrorCode.UNKNOWN_STATE.to_exception(
            message=f"未知的 {cls.__name__} code: {code!r}"
        )
