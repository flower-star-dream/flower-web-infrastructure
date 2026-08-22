"""
AOP 组件容器访问器

@Author: 花海
@Date: 2026/08/22 14:00
@Description: 供 AOP Advice 在运行时获取已装配组件（db/cache 等）。通过 ContextVar 承载当前
              应用组件字典（asyncio 场景安全），Application 装配完成时 bind_components 注入；
              与 RequestContext / 事务栈使用同一机理，避免 Advice 直接依赖全局单例。
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

#: 当前应用组件字典（app.state.components），默认空（未绑定）
_COMPONENTS: ContextVar[dict[str, Any]] = ContextVar("web_infra_aop_components", default={})


def bind_components(components: dict[str, Any]) -> None:
    """绑定当前应用的组件字典。

    由 Application 装配（build）完成后调用，供 Advice 在运行时按名取 db/cache 等组件。

    :param components: 组件字典（如 {"db": ..., "cache": ...}）
    """
    _COMPONENTS.set(components)


def get_component(name: str) -> Any | None:
    """按名取当前应用组件。

    :param name: 组件名（如 "db" / "cache"）
    :return: 组件对象；未绑定或不存在返回 None
    """
    return _COMPONENTS.get().get(name)


def all_components() -> dict[str, Any]:
    """返回当前应用组件字典的副本。

    供测试切片（mock_component）在"替换单个组件后回绑全量"时读取当前容器，
    避免直接修改容器对象。副本改动不影响容器原值，需通过 bind_components 回写生效。

    :return: 组件字典副本（如 {"db": ..., "cache": ...}）
    """
    return dict(_COMPONENTS.get())
