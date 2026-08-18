"""
扩展点装配校验结果

@Author: 花海
@Date: 2026/08/18 14:00
@Description: 扩展点装配校验结果：检查启用集合按依赖包含规则展开后的完整性
              （未知扩展点 / 依赖循环 → ok=False 并给出明细；缺前置不视为失败，
              按包含关系自动补足，见 closure / chain）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtensionValidation:
    """扩展点装配校验结果。

    :param ok: 是否通过（无未知扩展点且无依赖循环）
    :param unknown: 未注册的扩展点名集合
    :param circular: 依赖循环链路明细（每条为扩展点名序列）
    :param closure: 完整闭包（启用集合 + 自动补足的前置扩展点名集合）
    :param chain: 拓扑序扩展点名链（前置在前，目标最后）
    """

    ok: bool
    unknown: frozenset[str]
    circular: tuple[tuple[str, ...], ...]
    closure: frozenset[str]
    chain: tuple[str, ...]
