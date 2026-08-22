"""
测试上下文缓存

@Author: 花海
@Date: 2026/08/22 18:00
@Description: 测试上下文缓存（对标 Spring 测试上下文缓存）：按"配置指纹"缓存已装配测试上下文，
              同一 spec 多次构建复用，降低测试启动开销。供 pytest fixture 使用。
"""
from __future__ import annotations

from typing import Any

#: 缓存：配置指纹 -> TestContext（仅缓存无副作用组件子集）
test_context_cache: dict[tuple, Any] = {}


def get_context(settings: dict[str, Any], components: tuple[str, ...]):
    """按 (settings, components) 指纹取/建上下文（缓存命中直接复用）。

    :param settings: 配置字典（应用配置覆盖）
    :param components: 装配的组件名集合
    :return: 缓存命中直接复用，未命中则构建并写入缓存
    """
    key = (tuple(sorted(settings.items())), components)
    if key not in test_context_cache:
        from web_infra.testing.test_context import web_test_context

        test_context_cache[key] = web_test_context(settings, components=components)
    return test_context_cache[key]


def clear_cache() -> None:
    """清空测试上下文缓存（测试隔离用）。"""
    test_context_cache.clear()
