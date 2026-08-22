"""
AOP 声明式横切内核

@Author: 花海
@Date: 2026/08/22 14:00
@Description: 声明式横切能力（对标 Spring AOP）：切点匹配 + 通知 + 切面 + 装饰器织入。
              切面用 order 决定嵌套顺序（升序由外及里，同 order 按注册序兜底）；
              供声明式事务 / 缓存等横切统一织入，替代散落的装饰器与中间件。
"""
from web_infra.core.aop.pointcut import Pointcut
from web_infra.core.aop.advice import Advice, AdviceType
from web_infra.core.aop.aspect import Aspect
from web_infra.core.aop.aspect_registry import AspectRegistry
from web_infra.core.aop.weaver import AspectWeaver, aspect
from web_infra.core.aop.component_registry import bind_components, get_component, all_components

__all__ = [
    "Pointcut",
    "Advice",
    "AdviceType",
    "Aspect",
    "AspectRegistry",
    "AspectWeaver",
    "aspect",
    "bind_components",
    "get_component",
    "all_components",
]
