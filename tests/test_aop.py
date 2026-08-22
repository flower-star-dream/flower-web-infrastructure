"""
AOP 内核单元测试

@Author: 花海
@Date: 2026/08/22 14:00
@Description: 验证切点匹配（module/class/method 正则 + 参数类型）、Advice 类型、
              切面结构与 AspectRegistry 类级注册（同 order 按注册序兜底）。
"""
import pytest

from web_infra.core.aop.advice import Advice, AdviceType
from web_infra.core.aop.aspect import Aspect
from web_infra.core.aop.aspect_registry import AspectRegistry
from web_infra.core.aop.pointcut import Pointcut


class _Model:
    """切点参数类型样本"""


def test_pointcut_matches_method_name():
    """切点 method 正则匹配方法名"""
    pc = Pointcut(method=r"^do_\w+$")
    assert pc.matches("service.order.create_order") is False  # 方法名需单独验证
    assert pc.matches_method("do_work") is True
    assert pc.matches_method("run_do_thing") is False


def test_pointcut_matches_class_and_module():
    """切点 module/class 正则匹配"""
    pc = Pointcut(module=r"^service\.order$", class_=r"^OrderService$")
    assert pc.matches("service.order.OrderService.create_order") is True
    assert pc.matches("service.user.UserService.create_user") is False


def test_pointcut_argument_type_match():
    """切点参数类型匹配（按位置取第一个参数类型）"""
    pc = Pointcut(arg_types=("_Model",))
    assert pc.matches_args((_Model(),)) is True
    assert pc.matches_args(("not-model",)) is False


def test_advice_type_enum():
    """AdviceType 枚举值"""
    assert AdviceType.BEFORE.value == "BEFORE"
    assert AdviceType.AFTER.value == "AFTER"
    assert AdviceType.AFTER_RETURNING.value == "AFTER_RETURNING"
    assert AdviceType.AFTER_THROWING.value == "AFTER_THROWING"
    assert AdviceType.AROUND.value == "AROUND"


def test_aspect_holds_pointcut_and_advices():
    """切面 = 切点 + 一组通知（按元组顺序）"""
    advice = Advice(type=AdviceType.BEFORE, fn=lambda ctx: None, order=1)
    aspect = Aspect(name="tx", pointcut=Pointcut(method=r"^create_"), advices=(advice,))
    assert aspect.name == "tx"
    assert aspect.pointcut.matches_method("create_order") is True
    assert aspect.advices == (advice,)


def test_aspect_registry_same_order_by_registration():
    """同 order 按注册序兜底（先注册先返回），保证跨进程稳定"""
    from web_infra.core.aop.aspect_registry import _clear

    _clear()

    def _noop(ctx):
        return None

    a_first = Aspect("a", Pointcut(method=r"^create_"), (Advice(AdviceType.AROUND, _noop, order=0),))
    b_second = Aspect("b", Pointcut(method=r"^create_"), (Advice(AdviceType.AROUND, _noop, order=0),))
    AspectRegistry.register(a_first)
    AspectRegistry.register(b_second)
    chain = AspectRegistry.matching(Pointcut(method=r"^create_"), "_Model")
    assert [a.name for a in chain] == ["a", "b"]  # 注册序稳定
    _clear()


def test_aspect_registry_registration_order_sorting():
    """order 升序 -> 从小到大（外层先）；同 order 用注册序"""
    from web_infra.core.aop.aspect_registry import _clear

    _clear()

    def _noop(ctx):
        return None

    # 切面间嵌套排序用 Aspect.order（与已确认修正一致；同 order 按注册序兜底）
    AspectRegistry.register(Aspect("tx", Pointcut(method=r"^create_"), (Advice(AdviceType.AROUND, _noop),), order=1))
    AspectRegistry.register(Aspect("audit", Pointcut(method=r"^create_"), (Advice(AdviceType.AROUND, _noop),), order=2))
    AspectRegistry.register(Aspect("limit", Pointcut(method=r"^create_"), (Advice(AdviceType.AROUND, _noop),), order=1))
    chain = AspectRegistry.matching(Pointcut(method=r"^create_"), "_Model")
    assert [a.name for a in chain] == ["tx", "limit", "audit"]  # tx,limit 同 order=1 按注册序
    _clear()


# ---- 以下为 Task 2：AOP 织入器（AspectWeaver + 组件访问器）测试 ----

import asyncio

from web_infra.core.aop import AspectWeaver, aspect, bind_components, get_component


class _Ctx:
    """织入上下文替身（供 advice 校验 ctx.proceed）"""


order_log: list[str] = []


def test_weave_around_order_outer_first():
    """AROUND：order 小的先进入（外层），后退出（内层）"""
    from web_infra.core.aop import AspectRegistry, Aspect, Pointcut, Advice, AdviceType

    def _noop(*args):
        return None

    def _wrap_outer(ctx):
        order_log.append("outer-enter")
        result = ctx.proceed(*ctx.args, **ctx.kwargs)
        order_log.append("outer-exit")
        return result

    def _wrap_inner(ctx):
        order_log.append("inner-enter")
        result = ctx.proceed(*ctx.args, **ctx.kwargs)
        order_log.append("inner-exit")
        return result

    AspectRegistry.register(Aspect("outer", Pointcut(method=r"^run_"), (Advice(AdviceType.AROUND, _wrap_outer),), order=1))
    AspectRegistry.register(Aspect("inner", Pointcut(method=r"^run_"), (Advice(AdviceType.AROUND, _wrap_inner),), order=2))

    @aspect
    def run_worker():
        order_log.append("worker")

    order_log.clear()
    run_worker()
    assert order_log == ["outer-enter", "inner-enter", "worker", "inner-exit", "outer-exit"]

    from web_infra.core.aop.aspect_registry import _clear

    _clear()


def test_weave_sync_value_returned():
    """同步织入：返回值透传"""

    @aspect
    def add(a, b):
        return a + b

    assert add(1, 2) == 3


def test_weave_async_function():
    """异步织入：async 函数原样支持，await 返回结果"""
    from web_infra.core.aop import AspectRegistry, Aspect, Pointcut, Advice, AdviceType

    def _around(ctx):
        async def _run():
            result = await ctx.proceed(*ctx.args, **ctx.kwargs)
            return result

        return _run()

    AspectRegistry.register(Aspect("a", Pointcut(method=r"^fetch_"), (Advice(AdviceType.AROUND, _around),), order=0))

    @aspect
    async def fetch_demo(x):
        return x * 2

    assert asyncio.run(fetch_demo(21)) == 42

    from web_infra.core.aop.aspect_registry import _clear

    _clear()


def test_bind_components_and_get():
    """组件容器访问器：bind_components 后取 db/cache"""
    bind_components({"db": "fake-db", "cache": "fake-cache"})
    assert get_component("db") == "fake-db"
    assert get_component("cache") == "fake-cache"
