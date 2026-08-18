"""
基础启停状态机

@Author: 花海
@Date: 2026/08/16 16:00
@Description: 开箱即用的启用/禁用基础状态机；
              状态翻转计算在此完成，持久化由调用方负责（引擎不触碰持久层）。
              使用约定：params 需携带 key="entity" 的实体（须有 status 字段，值为 BaseStatus）。
"""
from __future__ import annotations

from typing import Callable, TypeVar

from web_infra.capabilities.state_machine.base_event import BaseEvent
from web_infra.capabilities.state_machine.base_state import BaseState
from web_infra.capabilities.state_machine.state_machine_error import StateMachineErrorCode
from web_infra.capabilities.state_machine.state_route_params import StateRouteParams
from web_infra.capabilities.state_machine.state_router import StateRouter

T = TypeVar("T")


class BaseStatus(BaseState):
    """基础状态：禁用/启用"""

    DISABLE = (0, "禁用")
    ENABLE = (1, "启用")


class StartStopEvent(BaseEvent):
    """基础事件：启用/禁用切换"""

    START_OR_STOP = (0, "启用或禁用")


class BaseStatusRouter(StateRouter[BaseStatus, StartStopEvent, T]):
    """基础启停路由：启用<->禁用互转；params 需携带 entity（含 status 字段的实体）"""

    def get_state_event_target_config(self) -> dict[BaseStatus, dict[StartStopEvent, BaseStatus]]:
        """合法流转表：ENABLE <-> DISABLE"""
        return {
            BaseStatus.ENABLE: {StartStopEvent.START_OR_STOP: BaseStatus.DISABLE},
            BaseStatus.DISABLE: {StartStopEvent.START_OR_STOP: BaseStatus.ENABLE},
        }

    def get_event_dispatcher(self) -> dict[StartStopEvent, Callable[[BaseStatus, StateRouteParams], BaseStatus]]:
        """事件处理器：按当前状态翻转实体并返回目标状态"""
        return {StartStopEvent.START_OR_STOP: self._start_or_stop}

    def _start_or_stop(self, current_state: BaseStatus, params: StateRouteParams) -> BaseStatus:
        """翻转实体状态；params 缺 entity 抛 EMPTY_PARAMETER"""
        entity = params.get_param("entity")
        if entity is None:
            raise StateMachineErrorCode.EMPTY_PARAMETER.to_exception(message="params 缺少 entity")
        target = BaseStatus.DISABLE if current_state is BaseStatus.ENABLE else BaseStatus.ENABLE
        entity.status = target
        return target
