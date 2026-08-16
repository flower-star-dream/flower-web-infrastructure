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
from web_infra.state_machine.base_status import BaseStatus, BaseStatusRouter, StartStopEvent
from web_infra.state_machine.state_machine import StateMachine
from web_infra.state_machine.state_machine_engine import StateMachineEngine
from web_infra.state_machine.state_machine_error import (
    StateMachineErrorCode,
    StateMachineErrorCodeEnum,
)
from web_infra.state_machine.state_machine_registry import StateMachineRegistry
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


@StateMachineRegistry.register
class _RegisteredRouter(StateRouter[_DemoStatus, _DemoEvent, _DemoEntity]):
    """通过装饰器注册的演示路由"""

    def get_state_event_target_config(self):
        return {_DemoStatus.PENDING: {_DemoEvent.SUBMIT: _DemoStatus.DONE}}

    def get_event_dispatcher(self):
        return {_DemoEvent.SUBMIT: lambda current_state, params: _DemoStatus.DONE}


class _OtherEntity:
    """另一个数据实体（用于未注册/重复注册场景）"""


class _SpiEntity:
    """用于引擎工厂 SPI 测试的数据实体"""


def test_registry_get_returns_engine():
    """get：返回已注册 key 的状态机引擎实例"""
    engine = StateMachineRegistry.get(_DemoStatus, _DemoEvent, _DemoEntity)
    assert isinstance(engine, StateMachine)
    assert isinstance(engine, StateMachineEngine)


def test_registry_get_cache_same_instance():
    """get：同一 key 缓存同一实例"""
    assert (
        StateMachineRegistry.get(_DemoStatus, _DemoEvent, _DemoEntity)
        is StateMachineRegistry.get(_DemoStatus, _DemoEvent, _DemoEntity)
    )


def test_registry_get_unregistered_raises():
    """get：未注册 key 抛 KeyError"""
    with pytest.raises(KeyError):
        StateMachineRegistry.get(_DemoStatus, _DemoEvent, _OtherEntity)


def test_registry_duplicate_register_raises():
    """register：同 key 重复注册抛 ValueError"""

    class _DuplicateRouter(StateRouter[_DemoStatus, _DemoEvent, _DemoEntity]):
        def get_state_event_target_config(self):
            return {}

        def get_event_dispatcher(self):
            return {}

    with pytest.raises(ValueError):
        StateMachineRegistry.register(_DuplicateRouter)


def test_registry_register_instance():
    """register_instance：已装配实例直接注册并可用（构造注入场景）"""

    class _InstanceRouter(StateRouter[_DemoStatus, _DemoEvent, _OtherEntity]):
        def __init__(self, prefix):
            self._prefix = prefix

        def get_state_event_target_config(self):
            return {_DemoStatus.PENDING: {_DemoEvent.SUBMIT: _DemoStatus.DONE}}

        def get_event_dispatcher(self):
            return {_DemoEvent.SUBMIT: lambda current_state, params: _DemoStatus.DONE}

    router = _InstanceRouter(prefix="x")
    registered = StateMachineRegistry.register_instance(router)
    assert registered is router
    engine = StateMachineRegistry.get(_DemoStatus, _DemoEvent, _OtherEntity)
    assert engine.fire(_DemoStatus.PENDING, _DemoEvent.SUBMIT, StateRouteParams.create()) is _DemoStatus.DONE


def test_registry_validate_router_missing_handler():
    """静态校验：组合表声明的事件无处理器，register_instance 立即抛 ValueError"""

    class _BrokenRouter(StateRouter[_DemoStatus, _DemoEvent, _SpiEntity]):
        def get_state_event_target_config(self):
            return {_DemoStatus.PENDING: {_DemoEvent.SUBMIT: _DemoStatus.DONE}}

        def get_event_dispatcher(self):
            return {}

    with pytest.raises(ValueError):
        StateMachineRegistry.register_instance(_BrokenRouter())


def test_registry_validate_router_on_get():
    """静态校验：register 装饰器注册后，get 首次实例化时同样校验"""

    class _BrokenRouter2(StateRouter[_DemoStatus, _DemoEvent, _SpiEntity]):
        def get_state_event_target_config(self):
            return {_DemoStatus.PENDING: {_DemoEvent.SUBMIT: _DemoStatus.DONE}}

        def get_event_dispatcher(self):
            return {}

    StateMachineRegistry.register(_BrokenRouter2)
    with pytest.raises(ValueError):
        StateMachineRegistry.get(_DemoStatus, _DemoEvent, _SpiEntity)


def test_registry_engine_factory_spi():
    """register_engine_factory：自定义引擎（第三方库适配）替换默认实现"""

    class _ThirdPartyEngine(StateMachineEngine[_DemoStatus, _DemoEvent]):
        """模拟基于第三方状态机库的适配引擎"""

        def __init__(self):
            self.calls = 0

        def fire(self, current_state, event, params=None):
            self.calls += 1
            return _DemoStatus.DONE

        async def fire_async(self, current_state, event, params=None):
            self.calls += 1
            return _DemoStatus.DONE

    StateMachineRegistry.register_engine_factory(_DemoStatus, _DemoEvent, _SpiEntity, _ThirdPartyEngine)
    engine = StateMachineRegistry.get(_DemoStatus, _DemoEvent, _SpiEntity)
    assert isinstance(engine, _ThirdPartyEngine)
    assert engine.fire(_DemoStatus.PENDING, _DemoEvent.SUBMIT, StateRouteParams.create()) is _DemoStatus.DONE
    assert engine.calls == 1


class _StatusEntity:
    """带 status 字段的简单实体"""

    def __init__(self, status):
        self.status = status


def test_base_status_router_enable_to_disable():
    """BaseStatusRouter：ENABLE + START_OR_STOP -> DISABLE，实体状态同步翻转"""
    entity = _StatusEntity(status=BaseStatus.ENABLE)
    engine = StateMachine(BaseStatusRouter())
    target = engine.fire(
        BaseStatus.ENABLE, StartStopEvent.START_OR_STOP, StateRouteParams().add_param("entity", entity)
    )
    assert target is BaseStatus.DISABLE
    assert entity.status is BaseStatus.DISABLE


def test_base_status_router_disable_to_enable():
    """BaseStatusRouter：DISABLE + START_OR_STOP -> ENABLE"""
    entity = _StatusEntity(status=BaseStatus.DISABLE)
    engine = StateMachine(BaseStatusRouter())
    target = engine.fire(
        BaseStatus.DISABLE, StartStopEvent.START_OR_STOP, StateRouteParams().add_param("entity", entity)
    )
    assert target is BaseStatus.ENABLE
    assert entity.status is BaseStatus.ENABLE


def test_base_status_router_missing_entity():
    """BaseStatusRouter：缺 entity 抛 EMPTY_PARAMETER"""
    engine = StateMachine(BaseStatusRouter())
    with pytest.raises(BizException) as ei:
        engine.fire(BaseStatus.ENABLE, StartStopEvent.START_OR_STOP, StateRouteParams.create())
    assert ei.value.code == "E4-STATE-002"


def test_web_infra_top_level_exports():
    """web_infra 顶层导出状态机核心类"""
    import web_infra

    assert web_infra.StateMachine is StateMachine
    assert web_infra.StateMachineEngine is StateMachineEngine
    assert web_infra.StateRouter is StateRouter
    assert web_infra.StateMachineRegistry is StateMachineRegistry
    assert web_infra.BaseState is BaseState
    assert web_infra.BaseEvent is BaseEvent
    assert web_infra.StateRouteParams is StateRouteParams
    assert web_infra.StateMachineErrorCode is StateMachineErrorCode
    assert web_infra.BaseStatus is BaseStatus
    assert web_infra.BaseStatusRouter is BaseStatusRouter
    assert web_infra.StartStopEvent is StartStopEvent
