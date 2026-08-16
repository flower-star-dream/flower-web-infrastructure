"""
状态机引擎接口（SPI）

@Author: 花海
@Date: 2026/08/16 16:00
@Description: 状态机引擎 SPI（Protocol）：定义 fire/fire_async 契约；默认实现为 StateMachine，
              业务可基于其他成熟状态机库（如 transitions）实现本协议并通过
              StateMachineRegistry.register_engine_factory 注册替换，遵循框架 SPI 惯例。
"""
from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from web_infra.state_machine.state_route_params import StateRouteParams

S = TypeVar("S")
E = TypeVar("E")


@runtime_checkable
class StateMachineEngine(Protocol[S, E]):
    """状态机引擎契约（SPI）：触发流转并返回目标状态"""

    def fire(self, current_state: S | None, event: E, params: StateRouteParams | None = None) -> S:
        """触发状态流转（同步处理器）并返回目标状态。"""

    async def fire_async(self, current_state: S | None, event: E, params: StateRouteParams | None = None) -> S:
        """触发状态流转（支持同步/异步处理器）并返回目标状态。"""
