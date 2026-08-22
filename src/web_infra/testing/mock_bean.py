"""
组件替身注入

@Author: 花海
@Date: 2026/08/22 18:00
@Description: 组件替身注入（对标 @MockBean）：用测试替身对象替换指定组件（如 db/redis/mq），
              供被测函数经 AOP 组件访问器取到替身。基于 all_components 取当前全量组件副本、
              替换单组件后 bind_components 回绑，未替换组件保持原值。
"""
from __future__ import annotations

from typing import Any, Callable, TypeVar

from web_infra.core.aop import all_components, bind_components

R = TypeVar("R")


def mock_component(component_name: str) -> Callable[[Callable[..., R]], Callable[..., R]]:
    """装饰一个"返回替身的函数"，并把 AOP 组件容器中该组件替换为替身产物。

    :param component_name: 被替换的组件名（如 "cache" / "db" / "mq"）
    """

    def _install(fake: R) -> None:
        """基于当前全量组件副本替换单组件并回绑，未替换组件保持原值。"""
        components = all_components()
        components[component_name] = fake
        bind_components(components)

    def _decorator(factory: Callable[..., R]) -> Callable[..., R]:
        def _wrapper(*args: Any, **kwargs: Any) -> R:
            fake = factory(*args, **kwargs)
            _install(fake)
            return fake

        # 装饰时即装配替身（对标 Spring @MockBean 在测试前注册），并保持函数可调用
        _install(factory())
        return _wrapper

    return _decorator
