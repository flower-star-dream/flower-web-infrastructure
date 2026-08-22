"""
AOP 装饰器织入器

@Author: 花海
@Date: 2026/08/22 14:00
@Description: AspectWeaver 基于装饰器织入（对标 Spring 但采用 Python 装饰器实现）：
              按目标方法名从 AspectRegistry 取全部命中切面（用切面自身 pointcut.matches 命中，
              再按 (order, 注册序) 排序），从最小 order 开始倒序 wrap（reversed），使最小 order
              的切面处于最外层（执行时先进入）。同步/异步函数统一支持（inspect.iscoroutinefunction 分支）。
"""
from __future__ import annotations

import functools
import inspect
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

from web_infra.core.aop.aspect import Aspect
from web_infra.core.aop.aspect_registry import AspectRegistry


@dataclass
class AspectContext:
    """织入上下文：暴露目标 args/kwargs 与 proceed（调用下一层切面或业务方法）。

    :param args: 方法位置参数
    :param kwargs: 方法关键字参数
    :param proceed: 下一层调用函数（返回可调用；async 时返回 awaitable）
    """

    args: tuple
    kwargs: dict
    proceed: Callable


class AspectWeaver:
    """AOP 织入器（装饰器织入，instance 单例）。"""

    _instance: ClassVar["AspectWeaver"] | None = None

    @classmethod
    def instance(cls) -> "AspectWeaver":
        """获取织入器单例。

        :return: AspectWeaver 实例
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def weave(self, fn: Callable) -> Callable:
        """织入目标函数：命中切面则按 (order, 注册序) 链倒序 wrap。

        :param fn: 目标函数
        :return: 包装后的函数；未命中切面则原样返回
        """
        target = self._target_name(fn)
        aspects = self._matching_by_target(target)
        if not aspects:
            return fn
        return self._build_chain(aspects, fn)

    def _build_chain(self, aspects: list[Aspect], fn: Callable) -> Callable:
        """按切面链倒序 wrap：aspects 已按 order 升序（最小在最外），从最后一个开始包。

        :param aspects: 命中且已排序的切面链
        :param fn: 目标函数
        :return: 嵌套包装后的函数
        """
        current = fn
        for aspect in reversed(aspects):
            current = self._wrap(aspect, current)
        return current

    def _wrap(self, aspect: Aspect, next_fn: Callable) -> Callable:
        """单个切面包装：仅保留该切面的通知组驱动逻辑。

        :param aspect: 切面
        :param next_fn: 下一层函数
        :return: 包装后的函数
        """

        @functools.wraps(next_fn)
        def _wrapper(*args: Any, **kwargs: Any):
            return self._run(
                aspect, next_fn, args, kwargs, is_async=inspect.iscoroutinefunction(next_fn)
            )

        return _wrapper

    def _run(
        self, aspect: Aspect, next_fn: Callable, args: tuple, kwargs: dict, *, is_async: bool
    ) -> Any:
        """按切面通知组调度执行。

        约定：AROUND 通过 ctx.proceed 控制下一层；BEFORE 前置；AFTER/AFTER_RETURNING/AFTER_THROWING
        按顺序在方法执行后触发。此处以 AROUND 为主链路：若存在 AROUND 通知，由它调用 proceed；
        否则内联执行 BEFORE/AFTER 组合。

        :param aspect: 当前切面
        :param next_fn: 下一层函数
        :param args: 位置参数
        :param kwargs: 关键字参数
        :param is_async: 是否为异步函数
        :return: 调度结果（异步时为 awaitable）
        """
        advices = sorted(aspect.advices, key=lambda a: a.order)

        if is_async:
            return self._run_async(aspect, advices, next_fn, args, kwargs)

        def proceed(*a, **kw):
            return next_fn(*a, **kw)

        return self._dispatch(advices, args, kwargs, proceed)

    def _dispatch(self, advices: list, args: tuple, kwargs: dict, proceed: Callable) -> Any:
        """同步分派：无 AROUND 时顺序执行 before -> fn -> after；有 AROUND 时由它调用 proceed。

        :param advices: 当前切面通知组（已按 order 升序）
        :param args: 位置参数
        :param kwargs: 关键字参数
        :param proceed: 下一层调用函数
        :return: 执行结果
        """
        around = [a for a in advices if a.type.value == "AROUND"]
        if not around:
            before = [a.fn for a in advices if a.type.value == "BEFORE"]
            after = [a.fn for a in advices if a.type.value == "AFTER"]
            try:
                for b in before:
                    b(AspectContext(args, kwargs, proceed))
                return proceed(*args, **kwargs)
            finally:
                for a in after:
                    a(AspectContext(args, kwargs, proceed))
        ctx = AspectContext(args, kwargs, proceed)
        return around[0].fn(ctx)

    async def _run_async(
        self, aspect: Aspect, advices: list, next_fn: Callable, args: tuple, kwargs: dict
    ) -> Any:
        """异步分派：proceed 返回 awaitable，await 后继续；AROUND 由内部返回 awaitable。

        :param aspect: 当前切面
        :param advices: 当前切面通知组（已按 order 升序）
        :param next_fn: 下一层函数
        :param args: 位置参数
        :param kwargs: 关键字参数
        :return: 执行结果
        """

        async def proceed(*a, **kw):
            result = next_fn(*a, **kw)
            if inspect.isawaitable(result):
                result = await result
            return result

        around = [a for a in advices if a.type.value == "AROUND"]
        if not around:
            before = [a.fn for a in advices if a.type.value == "BEFORE"]
            after = [a.fn for a in advices if a.type.value == "AFTER"]
            try:
                for b in before:
                    b(AspectContext(args, kwargs, proceed))
                return await proceed(*args, **kwargs)
            finally:
                for a in after:
                    a(AspectContext(args, kwargs, proceed))
        ctx = AspectContext(args, kwargs, proceed)
        result = around[0].fn(ctx)
        if inspect.isawaitable(result):
            result = await result
        return result

    def _target_name(self, fn: Callable) -> str:
        """目标函数完整名（module.Class.method）：供切点匹配。

        :param fn: 目标函数
        :return: 完整名
        """
        module = getattr(fn, "__module__", "")
        qualname = getattr(fn, "__qualname__", getattr(fn, "__name__", ""))
        return f"{module}.{qualname}"

    def _matching_by_target(self, target: str) -> list[Aspect]:
        """遍历 AspectRegistry 全量切面，用切面自身 pointcut 命中，再按 (order, 注册序) 排序。

        :param target: 目标完整名
        :return: 命中且已排序的切面链
        """
        aspects = list(AspectRegistry._aspects.values())
        hit = [aspect for aspect in aspects if aspect.pointcut.matches(target)]
        order = {aspect.name: i for i, aspect in enumerate(aspects)}
        hit.sort(key=lambda a: (a.order, order[a.name]))
        return hit


def aspect(fn: Callable) -> Callable:
    """业务入口装饰器：织入命中切面。

    :param fn: 目标函数
    :return: 织入后的函数
    """
    return AspectWeaver.instance().weave(fn)
