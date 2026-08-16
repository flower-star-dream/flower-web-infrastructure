"""
状态路由参数容器

@Author: 花海
@Date: 2026/08/16 16:00
@Description: 状态路由参数容器，承载任意数量/任意类型的参数，对应 flower-spring-cloud StateRouteParams。
"""
from __future__ import annotations

from typing import Any


class StateRouteParams:
    """状态路由参数容器：链式 add_param / get_param / contains / size"""

    def __init__(self) -> None:
        self._params: dict[str, Any] = {}

    def add_param(self, key: str, value: Any) -> "StateRouteParams":
        """添加路由参数，返回自身支持链式调用"""
        self._params[key] = value
        return self

    def get_param(self, key: str, default: Any = None) -> Any:
        """按 key 取参数；不存在返回 default"""
        return self._params.get(key, default)

    def contains(self, key: str) -> bool:
        """是否包含指定参数"""
        return key in self._params

    def size(self) -> int:
        """当前参数数量"""
        return len(self._params)

    @classmethod
    def create(cls) -> "StateRouteParams":
        """创建新的参数容器实例"""
        return cls()
