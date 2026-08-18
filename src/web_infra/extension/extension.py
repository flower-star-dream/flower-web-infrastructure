"""
扩展点契约

@Author: 花海
@Date: 2026/08/18 14:00
@Description: 统一扩展点契约（插件协议对象）：声明扩展点名称、说明、前置扩展点与生命周期钩子
              （build 装配期构建实例 / startup 启动钩子 / shutdown 停机钩子）。
              框架只负责契约与编排（ExtensionRegistry 注册、依赖校验、按序调用钩子），
              具体实现由业务插件提供（如新数据源、第三方 SDK、横切能力）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

#: 装配期构建器签名：入参扩展点配置段（app.extensions.<name>）与装配上下文
#: （{"settings": Settings, "components": 已装配组件 dict}），返回插件实例（任意资源对象）
ExtensionBuilder = Callable[[dict[str, Any], dict[str, Any]], Any]

#: 生命周期钩子签名：入参 build 产物（未提供 build 时为 None），同步/异步皆可
ExtensionHook = Callable[[Any], Any]


@dataclass(frozen=True)
class ExtensionPoint:
    """扩展点契约：声明插件名称、说明、前置扩展点与生命周期钩子。

    :param name: 扩展点名（注册表键，与 app.extensions.enabled 匹配）
    :param description: 扩展点说明
    :param requires: 前置扩展点名（按拓扑序先启用；未知/循环装配期快速失败）
    :param build: 装配期构建器（可省略）；入参 (options, ctx)，返回插件实例，
                  实例挂 app.state.extensions 供业务访问
    :param startup: 启动钩子（可省略）；入参 build 产物，应用启动时按拓扑序调用
    :param shutdown: 停机钩子（可省略）；入参 build 产物，应用停机时按逆拓扑序调用
    """

    name: str
    description: str = ""
    requires: tuple[str, ...] = ()
    build: ExtensionBuilder | None = None
    startup: ExtensionHook | None = None
    shutdown: ExtensionHook | None = None
