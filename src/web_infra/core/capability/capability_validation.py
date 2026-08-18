"""
能力装配校验结果

@Author: 花海
@Date: 2026/08/17 16:00
@Description: 能力装配校验（validate）结果：未知能力 / 依赖循环明细，以及按包含关系展开后的完整闭包与拓扑序。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityValidation:
    """能力装配校验结果。

    :param ok: 校验是否通过（无未知能力、无依赖循环）
    :param unknown: 未注册的能力名集合
    :param circular: 依赖循环链路（每条为能力名元组，如 ("a", "b", "a")）
    :param closure: 启用集合按包含关系展开后的完整能力闭包（含传递前置）
    :param chain: 闭包的拓扑序（前置在前）
    """

    ok: bool
    unknown: frozenset[str]
    circular: tuple[tuple[str, ...], ...]
    closure: frozenset[str]
    chain: tuple[str, ...]
