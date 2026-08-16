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
from web_infra.state_machine.state_machine import StateMachine
from web_infra.state_machine.state_machine_engine import StateMachineEngine
from web_infra.state_machine.state_machine_error import (
    StateMachineErrorCode,
    StateMachineErrorCodeEnum,
)
from web_infra.state_machine.state_route_params import StateRouteParams
from web_infra.state_machine.state_router import StateRouter


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


class _DemoRouter(StateRouter[_DemoStatus, _DemoEvent, _DemoEntity]):
    """演示状态路由：PENDING + SUBMIT -> DONE"""

    def get_state_event_target_config(self):
        return {_DemoStatus.PENDING: {_DemoEvent.SUBMIT: _DemoStatus.DONE}}

    def get_event_dispatcher(self):
        return {_DemoEvent.SUBMIT: self._submit}

    def _submit(self, current_state, params):
        return _DemoStatus.DONE


def test_router_route_dispatches():
    """route：按事件分发到处理器（处理器收到当前状态）并返回目标状态"""
    router = _DemoRouter()
    assert router.route(_DemoEvent.SUBMIT, _DemoStatus.PENDING, StateRouteParams.create()) is _DemoStatus.DONE


def test_router_route_unregistered_event():
    """route：未注册事件抛 EVENT_ROUTER_ERROR"""
    with pytest.raises(BizException) as ei:
        _DemoRouter().route(_DemoEvent.CANCEL, _DemoStatus.PENDING, StateRouteParams.create())
    assert ei.value.code == "E4-STATE-003"


def test_router_dispatcher_receives_current_state():
    """dispatcher 处理器第一个参数为当前状态（同一事件可随状态分叉）"""
    received = []

    class _StateAwareRouter(_DemoRouter):
        def get_event_dispatcher(self):
            return {_DemoEvent.SUBMIT: self._record_submit}

        def _record_submit(self, current_state, params):
            received.append(current_state)
            return _DemoStatus.DONE

    router = _StateAwareRouter()
    router.route(_DemoEvent.SUBMIT, _DemoStatus.PENDING, StateRouteParams.create())
    assert received == [_DemoStatus.PENDING]


class _AsyncHandlerRouter(_DemoRouter):
    """async 处理器的演示路由"""

    def get_event_dispatcher(self):
        return {_DemoEvent.SUBMIT: self._async_submit}

    async def _async_submit(self, current_state, params):
        return _DemoStatus.DONE


@pytest.fixture
def demo_machine():
    """已装配的演示状态机"""
    return StateMachine(_DemoRouter())


def test_default_engine_implements_spi():
    """默认引擎实现 StateMachineEngine SPI（isinstance 可识别）"""
    assert isinstance(StateMachine(_DemoRouter()), StateMachineEngine)


def test_fire_ok(demo_machine):
    """fire：合法流转返回目标状态"""
    assert demo_machine.fire(_DemoStatus.PENDING, _DemoEvent.SUBMIT, StateRouteParams.create()) is _DemoStatus.DONE


def test_fire_illegal_transition(demo_machine):
    """fire：组合表不包含该事件抛 ILLEGAL_STATE_TRANSITION"""
    with pytest.raises(BizException) as ei:
        demo_machine.fire(_DemoStatus.DONE, _DemoEvent.SUBMIT, StateRouteParams.create())
    assert ei.value.code == "E4-STATE-000"


def test_fire_empty_state(demo_machine):
    """fire：状态为空抛 EMPTY_STATE"""
    with pytest.raises(BizException) as ei:
        demo_machine.fire(None, _DemoEvent.SUBMIT, StateRouteParams.create())
    assert ei.value.code == "E4-STATE-001"


def test_fire_empty_params(demo_machine):
    """fire：参数为空抛 EMPTY_PARAMETER"""
    with pytest.raises(BizException) as ei:
        demo_machine.fire(_DemoStatus.PENDING, _DemoEvent.SUBMIT, None)
    assert ei.value.code == "E4-STATE-002"


def test_fire_empty_target():
    """fire：处理器返回空目标状态抛 EMPTY_STATE"""

    class _EmptyTargetRouter(_DemoRouter):
        def get_event_dispatcher(self):
            return {_DemoEvent.SUBMIT: lambda current_state, params: None}

    with pytest.raises(BizException) as ei:
        StateMachine(_EmptyTargetRouter()).fire(
            _DemoStatus.PENDING, _DemoEvent.SUBMIT, StateRouteParams.create()
        )
    assert ei.value.code == "E4-STATE-001"


def test_fire_sync_handler_returns_coroutine_raises():
    """fire：同步入口遇 async 处理器抛 TypeError（提示改用 fire_async）"""
    with pytest.raises(TypeError):
        StateMachine(_AsyncHandlerRouter()).fire(
            _DemoStatus.PENDING, _DemoEvent.SUBMIT, StateRouteParams.create()
        )


def test_fire_illegal_transition_message_uses_description():
    """fire：非法流转错误消息用 description 而非枚举 str"""
    with pytest.raises(BizException) as ei:
        StateMachine(_DemoRouter()).fire(_DemoStatus.DONE, _DemoEvent.SUBMIT, StateRouteParams.create())
    assert "已完成" in ei.value.message
    assert "提交" in ei.value.message


@pytest.mark.asyncio
async def test_fire_async_with_async_handler():
    """fire_async：async 处理器正常流转"""
    machine = StateMachine(_AsyncHandlerRouter())
    assert await machine.fire_async(
        _DemoStatus.PENDING, _DemoEvent.SUBMIT, StateRouteParams.create()
    ) is _DemoStatus.DONE


@pytest.mark.asyncio
async def test_fire_async_with_sync_handler(demo_machine):
    """fire_async：同步处理器也可用"""
    assert await demo_machine.fire_async(
        _DemoStatus.PENDING, _DemoEvent.SUBMIT, StateRouteParams.create()
    ) is _DemoStatus.DONE


@pytest.mark.asyncio
async def test_fire_async_illegal_transition(demo_machine):
    """fire_async：非法流转抛 ILLEGAL_STATE_TRANSITION"""
    with pytest.raises(BizException) as ei:
        await demo_machine.fire_async(_DemoStatus.DONE, _DemoEvent.SUBMIT, StateRouteParams.create())
    assert ei.value.code == "E4-STATE-000"


def test_fire_supports_dynamic_state_value():
    """扩展状态：状态值不限于枚举（动态/无限状态场景，任意 hashable 值）"""

    class _DynamicRouter(StateRouter[tuple, str, _DemoEntity]):
        """重试状态机：状态为 ('RETRYING', 次数)，次数可无限增长"""

        def get_state_event_target_config(self):
            return {("RETRYING", 0): {"RETRY": ("RETRYING", 1)},
                    ("RETRYING", 1): {"RETRY": ("RETRYING", 2)}}

        def get_event_dispatcher(self):
            return {"RETRY": lambda current_state, params: ("RETRYING", current_state[1] + 1)}

    machine = StateMachine(_DynamicRouter())
    target = machine.fire(("RETRYING", 1), "RETRY", StateRouteParams.create())
    assert target == ("RETRYING", 2)
