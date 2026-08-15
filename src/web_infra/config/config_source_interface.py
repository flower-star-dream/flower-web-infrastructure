"""
统一配置源接口

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一配置源抽象接口：应用代码只依赖该接口，屏蔽本地/配置中心差异。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ConfigSourceInterface(Protocol):
    """统一配置源抽象接口：应用代码只依赖该接口，屏蔽本地/配置中心差异"""

    def get(self, key: str, default: Any = None) -> Any:
        """按 key 读取配置，不存在时返回 default"""
        ...

    def contains(self, key: str) -> bool:
        """判断配置项是否存在"""
        ...
