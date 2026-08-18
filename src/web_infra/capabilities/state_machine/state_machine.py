"""
状态机引擎（默认实现）

@Author: 花海
@Date: 2026/08/16 16:00
@Description: 状态机引擎默认实现；实现 StateMachineEngine SPI，
              只做流转合法性校验 + 事件分发，不触碰持久层（持久化由路由处理器自行完成）。
              校验顺序：状态非空 → 参数非空 → 组合表合法性 → 事件分发 → 目标状态非空。
"""
from __future__ import annotations

import inspect
from typing import Any, Coroutine, Generic, TypeVar, cast

from web_infra.capabilities.state_machine.state_machine_engine import StateMachineEngine
from web_infra.capabilities.state_machine.state_machine_error import StateMachineErrorCode
from web_infra.capabilities.state_machine.state_route_params import StateRouteParams
from web_infra.capabilities.state_machine.state_router import StateRouter

S = TypeVar("S")
E = TypeVar("E")
D = TypeVar("D")


def _state_label(value: Any) -> str:
    """状态/事件的可读标签：BaseState/BaseEvent 优先用 description，其余用 repr"""
    description = getattr(value, "description", None)
    return description if description else repr(value)


class StateMachine(Generic[S, E, D], StateMachineEngine[S, E]):
    """状态机引擎（默认实现）：流转合法性校验 + 事件分发，返回目标状态"""

    def __init__(self, router: StateRouter[S, E, D]) -> None:
        """初始化状态机。

        :param router: 状态路由（声明合法流转与事件处理器）
        """
        self._router = router

    def _validate(self, current_state: S | None, event: E, params: StateRouteParams | None) -> None:
        """通用校验：状态非空 → 参数非空 → 组合表合法性"""
        if current_state is None:
            raise StateMachineErrorCode.EMPTY_STATE.to_exception()
        if params is None:
            raise StateMachineErrorCode.EMPTY_PARAMETER.to_exception()
        event2target = self._router.get_state_event_target_config().get(current_state)
        if event2target is None or event not in event2target:
            raise StateMachineErrorCode.ILLEGAL_STATE_TRANSITION.to_exception(
                message=f"非法的状态流转: {_state_label(current_state)} + {_state_label(event)}"
            )

    def _ensure_target(self, target: S | None) -> S:
        """目标状态非空校验"""
        if target is None:
            raise StateMachineErrorCode.EMPTY_STATE.to_exception()
        return target

    def fire(self, current_state: S | None, event: E, params: StateRouteParams | None = None) -> S:
        """触发状态流转（同步处理器）。

        :param current_state: 当前状态（枚举成员或任意 hashable 值）
        :param event: 事件（枚举成员或任意 hashable 值）
        :param params: 路由参数容器（可为 None，会抛 EMPTY_PARAMETER）
        :return: 目标状态
        :raises BizException: EMPTY_STATE / EMPTY_PARAMETER / ILLEGAL_STATE_TRANSITION
        :raises TypeError: 处理器为 async 函数时（请改用 fire_async）
        """
        self._validate(current_state, event, params)
        assert current_state is not None and params is not None  # _validate 已保证非空（否则抛异常），此处仅供类型收窄
        target = self._router.route(event, current_state, params)
        if inspect.isawaitable(target):
            # 关闭未 await 的协程避免 ResourceWarning，再提示改用 fire_async
            cast("Coroutine[Any, Any, Any]", target).close()
            raise TypeError("同步 fire 不能处理 async 处理器，请改用 fire_async")
        return self._ensure_target(target)

    async def fire_async(self, current_state: S | None, event: E, params: StateRouteParams | None = None) -> S:
        """触发状态流转（支持同步/异步处理器）。

        :param current_state: 当前状态（枚举成员或任意 hashable 值）
        :param event: 事件（枚举成员或任意 hashable 值）
        :param params: 路由参数容器（可为 None，会抛 EMPTY_PARAMETER）
        :return: 目标状态
        :raises BizException: EMPTY_STATE / EMPTY_PARAMETER / ILLEGAL_STATE_TRANSITION
        """
        self._validate(current_state, event, params)
        assert current_state is not None and params is not None  # _validate 已保证非空（否则抛异常），此处仅供类型收窄
        target = self._router.route(event, current_state, params)
        if inspect.isawaitable(target):
            target = await target
        return self._ensure_target(target)
