"""
通用状态机模块

@Author: 花海
@Date: 2026/08/16 16:00
@Description: 通用状态机组件：状态/事件基类 + 路由抽象基类 + 引擎 SPI 与默认实现 + 注册表 + 基础启停状态机。
"""
from web_infra.state_machine.state_machine_error import (
    StateMachineErrorCode,
    StateMachineErrorCodeEnum,
)

__all__ = [
    "StateMachineErrorCode",
    "StateMachineErrorCodeEnum",
]
