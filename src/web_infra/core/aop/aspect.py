"""
AOP 切面定义

@Author: 花海
@Date: 2026/08/22 14:00
@Description: AOP 切面（对标 Spring @Aspect：切点 + 一组通知）。切面用 order 参予切面间
              嵌套排序（升序，从小到大由外及里）；切面内通知按 advices 元组顺序执行。
"""
from __future__ import annotations

from dataclasses import dataclass

from web_infra.core.aop.advice import Advice
from web_infra.core.aop.pointcut import Pointcut


@dataclass(frozen=True)
class Aspect:
    """AOP 切面：切点 + 一组通知。

    :param name: 切面名（注册表键；同 order 时按注册序兜底）
    :param pointcut: 切点匹配规则
    :param advices: 通知集合（按元组顺序执行）
    :param order: 切面间嵌套排序（升序，越小越外层；同 order 按注册序兜底）
    """

    name: str
    pointcut: Pointcut
    advices: tuple[Advice, ...]
    order: int = 0
