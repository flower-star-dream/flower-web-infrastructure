"""
事件枚举基类

@Author: 花海
@Date: 2026/08/16 16:00
@Description: 事件枚举基类（推荐便捷基类，非强制——引擎不要求事件必须继承本类），
              成员 value 即业务码（get_code()），
              description 返回中文名，of(code) 反查（未知码抛 UNKNOWN_STATE）。
"""
from __future__ import annotations

from enum import Enum

from web_infra.capabilities.state_machine.state_machine_error import StateMachineErrorCode


class BaseEvent(Enum):
    """事件枚举基类：业务侧 `class OrderEvent(BaseEvent): PAY = (1, "支付")` 声明"""

    _description_: str  # 实例属性类型声明（由 __new__ 写入，供静态检查识别，非枚举成员）

    def __new__(cls, code: int | str, description: str) -> "BaseEvent":
        obj = object.__new__(cls)
        obj._value_ = code
        obj._description_ = description
        return obj

    @property
    def description(self) -> str:
        """返回事件中文名"""
        return self._description_

    def get_code(self) -> int | str:
        """返回入库业务码（规范 §5.2：入库存 code 禁存枚举名）"""
        return self.value

    @classmethod
    def of(cls, code: int | str) -> "BaseEvent":
        """按业务码反查成员；未知码抛 UNKNOWN_STATE（E4-STATE-004）"""
        for member in cls:
            if member.value == code:
                return member
        raise StateMachineErrorCode.UNKNOWN_STATE.to_exception(
            message=f"未知的 {cls.__name__} code: {code!r}"
        )
