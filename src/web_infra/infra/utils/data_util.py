"""
通用数据工具

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 通用数据处理工具类：安全类型转换、集合与字典操作。
              数值处理（舍入/百分比/浮点比较等）统一收敛于 MathUtil 数学工具。
"""
from __future__ import annotations

from typing import Any


class DataUtil:
    """通用数据工具类：安全类型转换、集合与字典操作"""

    @staticmethod
    def to_int(value: Any, default: int = 0) -> int:
        """安全转换为整数，无法转换时返回默认值。

        :param value: 待转换的值
        :param default: 转换失败时的默认值
        :return: 整数
        """
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def to_float(value: Any, default: float = 0.0) -> float:
        """安全转换为浮点数，无法转换时返回默认值。

        :param value: 待转换的值
        :param default: 转换失败时的默认值
        :return: 浮点数
        """
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def to_bool(value: Any, default: bool = False) -> bool:
        """安全转换为布尔值，支持 true/false、1/0、yes/no、on/off 等常见表示。

        :param value: 待转换的值
        :param default: 无法识别时的默认值
        :return: 布尔值
        """
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on", "y"}:
                return True
            if normalized in {"false", "0", "no", "off", "n", ""}:
                return False
        return default

    @staticmethod
    def get_nested(data: dict[str, Any], key: str, default: Any = None, sep: str = ".") -> Any:
        """按点分隔 key 从嵌套字典安全取值，不存在时返回默认值。

        :param data: 嵌套字典
        :param key: 点分隔的键路径（如 a.b.c）
        :param default: 取值失败时的默认值
        :param sep: 键路径分隔符
        :return: 取到的值或默认值
        """
        if key in data:
            return data[key]
        current: Any = data
        for part in key.split(sep):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    @staticmethod
    def chunk(items: list, size: int) -> list[list]:
        """将列表按固定大小切分为多个子列表。

        :param items: 待分块的列表
        :param size: 每块大小（必须大于 0）
        :return: 子列表集合
        """
        if size <= 0:
            raise ValueError(f"size({size}) 必须大于 0")
        return [items[i:i + size] for i in range(0, len(items), size)]

    @staticmethod
    def unique(items: list) -> list:
        """列表去重（保持原顺序）。

        :param items: 待去重的列表
        :return: 去重后的列表
        """
        seen: set = set()
        result: list = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result
