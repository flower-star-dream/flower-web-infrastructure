"""
状态机错误码

@Author: 花海
@Date: 2026/08/16 16:00
@Description: 状态机引擎错误码定义（规范 §4 错误码体系 E4 业务域扩展）。
              权威定义见 StateMachineErrorCodeEnum，StateMachineErrorCode 类属性引用枚举成员值
              以保持对外 API 兼容，模块导入时登记到注册表（与 CommonErrorCode 模式一致）。
"""
from __future__ import annotations

import logging
from enum import Enum

from web_infra.infra.error.error_code import ErrorCode
from web_infra.infra.error.error_code_registry import ErrorCodeRegistry


class StateMachineErrorCodeEnum(Enum):
    """状态机错误码枚举（E4-STATE 域，HTTP 422，业务域 WARNING）"""

    ILLEGAL_STATE_TRANSITION = ErrorCode("E4-STATE-000", "非法的状态流转", 422, "E4", log_level=logging.WARNING)
    EMPTY_STATE = ErrorCode("E4-STATE-001", "状态不能为空", 422, "E4", log_level=logging.WARNING)
    EMPTY_PARAMETER = ErrorCode("E4-STATE-002", "状态路由参数不能为空", 422, "E4", log_level=logging.WARNING)
    EVENT_ROUTER_ERROR = ErrorCode("E4-STATE-003", "事件未注册路由处理器", 422, "E4", log_level=logging.WARNING)
    UNKNOWN_STATE = ErrorCode("E4-STATE-004", "未知的状态码/事件码", 422, "E4", log_level=logging.WARNING)


class StateMachineErrorCode:
    """状态机错误码定义——属性为枚举成员值，权威定义见 StateMachineErrorCodeEnum"""

    ILLEGAL_STATE_TRANSITION: ErrorCode = StateMachineErrorCodeEnum.ILLEGAL_STATE_TRANSITION.value
    EMPTY_STATE: ErrorCode = StateMachineErrorCodeEnum.EMPTY_STATE.value
    EMPTY_PARAMETER: ErrorCode = StateMachineErrorCodeEnum.EMPTY_PARAMETER.value
    EVENT_ROUTER_ERROR: ErrorCode = StateMachineErrorCodeEnum.EVENT_ROUTER_ERROR.value
    UNKNOWN_STATE: ErrorCode = StateMachineErrorCodeEnum.UNKNOWN_STATE.value


def _register_state_machine_codes() -> None:
    """将状态机错误码登记到注册表（遍历枚举注册，模块导入时执行一次）"""
    for member in StateMachineErrorCodeEnum:
        ErrorCodeRegistry.register(member.value)


# 模块导入时登记状态机错误码
_register_state_machine_codes()
