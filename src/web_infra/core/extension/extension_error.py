"""
扩展点异常

@Author: 花海
@Date: 2026/08/18 14:00
@Description: 统一扩展注册器专用异常：扩展点名空 / 依赖自身 / 同名冲突（未显式覆盖）/
              未注册扩展点 / 依赖循环，均由 ExtensionRegistry 抛 ExtensionError。
"""
from __future__ import annotations


class ExtensionError(Exception):
    """统一扩展注册器异常（注册/解析/装配校验失败）"""
