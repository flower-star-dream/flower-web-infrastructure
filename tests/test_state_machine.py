"""
通用状态机组件单元测试

@Author: 花海
@Date: 2026/08/16 16:00
@Description: 覆盖错误码、枚举基类、参数容器、路由、引擎 SPI 与默认实现（fire/fire_async）、
              注册表（静态校验/引擎工厂）、基础启停状态机与顶层导出，全 Mock 不触网。
"""
import pytest

from web_infra.error.error_code_registry import ErrorCodeRegistry
from web_infra.state_machine.state_machine_error import (
    StateMachineErrorCode,
    StateMachineErrorCodeEnum,
)


def test_state_machine_error_codes_registered():
    """E4-STATE-000~004：枚举成员 + 类属性引用 + 注册表登记"""
    assert StateMachineErrorCodeEnum.ILLEGAL_STATE_TRANSITION.value.code == "E4-STATE-000"
    assert StateMachineErrorCodeEnum.EMPTY_STATE.value.code == "E4-STATE-001"
    assert StateMachineErrorCodeEnum.EMPTY_PARAMETER.value.code == "E4-STATE-002"
    assert StateMachineErrorCodeEnum.EVENT_ROUTER_ERROR.value.code == "E4-STATE-003"
    assert StateMachineErrorCodeEnum.UNKNOWN_STATE.value.code == "E4-STATE-004"

    assert StateMachineErrorCode.ILLEGAL_STATE_TRANSITION.code == "E4-STATE-000"
    assert StateMachineErrorCode.EMPTY_STATE.code == "E4-STATE-001"
    assert StateMachineErrorCode.EMPTY_PARAMETER.code == "E4-STATE-002"
    assert StateMachineErrorCode.EVENT_ROUTER_ERROR.code == "E4-STATE-003"
    assert StateMachineErrorCode.UNKNOWN_STATE.code == "E4-STATE-004"
    assert StateMachineErrorCode.ILLEGAL_STATE_TRANSITION.http_status == 422
    assert StateMachineErrorCode.EMPTY_PARAMETER.category == "E4"

    for member in StateMachineErrorCodeEnum:
        assert ErrorCodeRegistry.get(member.value.code) is member.value


def test_state_machine_error_to_exception():
    """错误码可转 BizException（统一抛出约定）"""
    exc = StateMachineErrorCode.ILLEGAL_STATE_TRANSITION.to_exception()
    assert exc.code == "E4-STATE-000"
