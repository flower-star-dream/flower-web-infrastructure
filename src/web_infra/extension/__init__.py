"""
统一扩展注册器模块

@Author: 花海
@Date: 2026/08/18 14:00
@Description: 统一扩展注册器：为框架提供一致的扩展点契约（ExtensionPoint：build/startup/shutdown/requires）
              与生命周期编排。业务插件（新数据源、第三方 SDK、横切能力）经 ExtensionRegistry 注册后，
              在 app.extensions.enabled 声明即启用；装配期按拓扑序构建实例并挂 app.state.extensions，
              应用启动/停机按序调用生命周期钩子。
              与领域注册表（DatabaseRegistry 等）的边界：领域注册表按名管资源工厂（装配期实例化），
              扩展注册器管插件协议对象（生命周期 + 依赖顺序），两者互补不冲突。
"""
from __future__ import annotations

from web_infra.extension.extension import ExtensionPoint
from web_infra.extension.extension_error import ExtensionError
from web_infra.extension.extension_registry import ExtensionRegistry
from web_infra.extension.extension_resolution import ExtensionResolution
from web_infra.extension.extension_validation import ExtensionValidation

__all__ = [
    "ExtensionPoint",
    "ExtensionError",
    "ExtensionRegistry",
    "ExtensionResolution",
    "ExtensionValidation",
]
