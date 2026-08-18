"""
状态路由抽象基类

@Author: 花海
@Date: 2026/08/16 16:00
@Description: 状态路由抽象基类；业务侧实现两张声明表
              （状态×事件→目标、事件→处理器）即可，route 为统一分发入口。
              设计要点：S/E 不强制继承 BaseState/BaseEvent（支持扩展/动态状态值，须可 hash），
              处理器签名统一为 handler(current_state, params)，同一事件可按当前状态分叉。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Generic, TypeVar

from web_infra.capabilities.state_machine.state_machine_error import StateMachineErrorCode
from web_infra.capabilities.state_machine.state_route_params import StateRouteParams

S = TypeVar("S")
E = TypeVar("E")
D = TypeVar("D")


class StateRouter(ABC, Generic[S, E, D]):
    """状态路由抽象基类：声明合法流转 + 事件业务处理器（同步或 async 函数）"""

    @abstractmethod
    def get_state_event_target_config(self) -> dict[S, dict[E, S]]:
        """状态×事件 → 目标状态 合法组合表（引擎仅用于流转合法性校验，不强制目标一致）"""

    @abstractmethod
    def get_event_dispatcher(self) -> dict[E, Callable[[S, StateRouteParams], S]]:
        """事件 → 业务处理器（签名 handler(current_state, params)，返回目标状态；持久化由处理器自行完成）"""

    def route(self, event: E, current_state: S, params: StateRouteParams) -> S:
        """统一入口：按事件取处理器执行；未注册事件抛 EVENT_ROUTER_ERROR（E4-STATE-003）"""
        handler = self.get_event_dispatcher().get(event)
        if handler is None:
            raise StateMachineErrorCode.EVENT_ROUTER_ERROR.to_exception(
                message=f"事件 {event} 未注册路由处理器"
            )
        return handler(current_state, params)
