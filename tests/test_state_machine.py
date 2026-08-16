"""
通用状态机组件单元测试

@Author: 花海
@Date: 2026/08/16 16:00
@Description: 覆盖错误码、枚举基类、参数容器、路由、引擎 SPI 与默认实现（fire/fire_async）、
              注册表（静态校验/引擎工厂）、基础启停状态机与顶层导出，全 Mock 不触网。
"""
import pytest

from web_infra.error.biz_exception import BizException
from web_infra.error.error_code_registry import ErrorCodeRegistry
from web_infra.state_machine.base_event import BaseEvent
from web_infra.state_machine.base_state import BaseState
from web_infra.state_machine.state_machine_error import (
    StateMachineErrorCode,
    StateMachineErrorCodeEnum,
)
from web_infra.state_machine.state_route_params import StateRouteParams


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


class _DemoStatus(BaseState):
    """演示状态枚举"""
    PENDING = (1, "待处理")
    DONE = (2, "已完成")


class _DemoEvent(BaseEvent):
    """演示事件枚举"""
    SUBMIT = (10, "提交")
    CANCEL = (20, "取消")


class _DemoEntity:
    """演示数据实体（无 ORM 依赖）"""


def test_base_state_code_description():
    """BaseState：value 即业务码，description 返回中文名"""
    assert _DemoStatus.PENDING.value == 1
    assert _DemoStatus.PENDING.get_code() == 1
    assert _DemoStatus.PENDING.description == "待处理"


def test_base_state_of():
    """BaseState.of：反查成功 / 未知码抛 UNKNOWN_STATE"""
    assert _DemoStatus.of(1) is _DemoStatus.PENDING
    with pytest.raises(BizException) as ei:
        _DemoStatus.of(99)
    assert ei.value.code == "E4-STATE-004"


def test_base_event_of():
    """BaseEvent.of：反查成功 / 未知码抛 UNKNOWN_STATE"""
    assert _DemoEvent.of(10) is _DemoEvent.SUBMIT
    with pytest.raises(BizException) as ei:
        _DemoEvent.of(99)
    assert ei.value.code == "E4-STATE-004"


def test_state_route_params():
    """StateRouteParams：add/get/默认值/contains/size/create"""
    params = StateRouteParams.create().add_param("order_id", 1).add_param("remark", "x")
    assert params.get_param("order_id") == 1
    assert params.get_param("missing", "default") == "default"
    assert params.get_param("missing") is None
    assert params.contains("remark")
    assert not params.contains("none")
    assert params.size() == 2
