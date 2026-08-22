"""
测试自动回滚

@Author: 花海
@Date: 2026/08/22 18:00
@Description: 测试自动回滚（对标 Spring @Transactional 测试回滚）：在测试事务外层开启/复用事务，
              测试结束后回滚，不污染数据库。本计划为最小实现：包一层调用保证装饰器可调用，
              完整回滚与事务边界交互（db.session NESTED / open_transaction + rollback）可后续增强。
"""
from __future__ import annotations

from typing import Any, Callable, TypeVar

R = TypeVar("R")


def auto_rollback(fn: Callable[..., R]) -> Callable[..., R]:
    """装饰测试函数：测试结束（正常/异常）后回滚事务。

    当前为最小非破坏性实现：在函数执行外包一层，任何情况下不真正提交（由调用方控制）。
    完整回滚需与框架事务边界协作，后续增强。

    :param fn: 被装饰的测试函数
    :return: 包装后的函数
    """

    def _wrapper(*args: Any, **kwargs: Any) -> R:
        return fn(*args, **kwargs)

    return _wrapper
