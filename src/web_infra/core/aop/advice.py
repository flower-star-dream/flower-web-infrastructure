"""
AOP 通知定义

@Author: 花海
@Date: 2026/08/22 14:00
@Description: AOP 通知类型（对标 Spring AOP Advice 的 5 种 before/after/around）+ 通知载体。
              同一 Aspect 内多个通知按 advices 元组声明顺序执行（不设 per-advice order，
              避免与切面间 order 混淆）；order 仅用于切面之间嵌套排序。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

#: 通知处理签名：入参 AspectContext（定义于 weaver.py，作宽松类型避免运行期前向引用），
#: 返回任意值（AROUND 需自行调用 ctx.proceed()）
AdviceFn = Callable[[Any], Any]


class AdviceType(Enum):
    """通知类型（对齐 Spring AOP 通知语义）"""

    BEFORE = "BEFORE"                        # 方法执行前
    AFTER = "AFTER"                          # 方法执行后（无论成败）
    AFTER_RETURNING = "AFTER_RETURNING"      # 方法成功返回后
    AFTER_THROWING = "AFTER_THROWING"        # 方法抛异常后
    AROUND = "AROUND"                        # 包裹整个方法执行


@dataclass
class Advice:
    """AOP 通知：类型 + 处理函数 + 切面内顺序。

    :param type: 通知类型
    :param fn: 处理函数（入参 AspectContext）
    :param order: 切面内通知顺序（升序执行；同 Aspect 内按此值排序）
    """

    type: AdviceType
    fn: AdviceFn
    order: int = 0
