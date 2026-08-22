"""
声明式事务

@Author: 花海
@Date: 2026/08/22 15:00
@Description: @transactional 声明式事务（对标 Spring @Transactional）：以"装饰器直接织入"方式实现，
              不依赖 AspectRegistry 的全局切点匹配，直接复用现有事务传播栈
              （SessionScopeMixin.session / SqliteSessionFactory.session 的 propagation + current_session）。
              方法进入时开/加入事务，退出或异常时 commit/rollback（含 rollback-only 语义）；
              方法内用 current_session() 取当前事务会话执行 SQL。支持传播级别与隔离级别
              （isolation_level 仅对支持的环境透传，SQLite 静默忽略）。
"""
from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from web_infra.core.aop import Aspect, AspectRegistry, Pointcut, get_component
from web_infra.capabilities.db.transaction_propagation import Propagation

#: 内置事务切面名（供 register_tx_aspect 注册占位；@transactional 实际织入在装饰器内完成）
TX_ASPECT_NAME = "transactional"


def _open_session(db: Any, *, propagation: Propagation, isolation_level: str | None) -> Any:
    """打开事务会话：透传传播级别与隔离级别，并对"环境不支持隔离级别"做兼容。

    SQLite 参考实现 `SqliteSessionFactory.session()` 已落地为 `session(propagation=...)`
    （无 `isolation_level`，SQLite 无事务隔离级别概念，静默忽略）。因此统一在此探测目标
    `session` 是否接受 `isolation_level`：接受则透传，不接受则仅传 `propagation`
    （隔离级别静默忽略），避免 TypeError。MySQL/PostgreSQL 等支持隔离级别的实现可正常透传。

    :param db: 数据库组件（需暴露 session() 上下文管理器）
    :param propagation: 事务传播级别
    :param isolation_level: 会话级隔离级别（环境不支持时忽略）
    :return: 事务作用域异步上下文管理器
    """
    params = inspect.signature(db.session).parameters
    if "isolation_level" in params:
        return db.session(propagation=propagation, isolation_level=isolation_level)  # type: ignore[call-arg]
    return db.session(propagation=propagation)  # type: ignore[call-arg]


def register_tx_aspect(order: int = 1) -> None:
    """注册事务切面占位（模块导入即调用，幂等）。

    注意：@transactional 采用"装饰器直接织入"实现，不依赖 AspectRegistry 全局切点匹配；
    此切面仅作为占位登记（默认切点不匹配任何全局方法），保证事务语义可追溯并保留扩展空间
    （如未来接入切点声明式匹配）。重复调用时直接返回，不重复注册。

    :param order: 切面嵌套序（升序越小越外层；默认 1，保证事务包裹大多数内层切面）
    """
    if AspectRegistry.get(TX_ASPECT_NAME) is not None:
        return
    AspectRegistry.register(
        Aspect(
            name=TX_ASPECT_NAME,
            pointcut=Pointcut(),  # 默认不匹配任何全局方法（由装饰器显式织入）
            advices=(),
            order=order,
        ),
        overwrite=True,
    )


def transactional(
    fn: Callable[..., Any] | Propagation | None = None,
    *,
    propagation: Propagation = Propagation.REQUIRED,
    isolation_level: str | None = None,
) -> Callable[..., Any]:
    """声明式事务装饰器（可参数化：`@transactional` 裸写 与 `@transactional(...)` 均可用）。

    用法：
        @transactional                                  # 裸写：默认 REQUIRED
        @transactional(propagation=Propagation.REQUIRED, isolation_level=None)
    方法内用 `current_session()` 取当前事务会话执行 SQL；方法退出统一 commit，
    异常统一 rollback。方法上不注入 session 参数（业务自行经 current_session() 获取）。

    :param fn: 位置参数。None（缺省，走 `@transactional(...)` 工厂）；callable（`@transactional`
        裸写时的被装饰函数，默认 REQUIRED）；Propagation（`@transactional(Propagation.X)` 位置传传播级别）
    :param propagation: 事务传播级别（默认 REQUIRED，复用外层事务）
    :param isolation_level: 会话级隔离级别（仅建新事务时生效；环境不支持时忽略）
    :raises RuntimeError: 运行时取不到 db 组件（未 create_app / 未 bind_components）
    """

    # 裸写 `@transactional`：位置参数是被装饰函数 → 直接装饰（默认 REQUIRED）
    if callable(fn):
        return _make_decorator(propagation=propagation, isolation_level=isolation_level)(fn)
    # 位置传 Propagation（`@transactional(Propagation.X)`）：把它作为传播级别
    if isinstance(fn, Propagation):
        propagation = fn
    return _make_decorator(propagation=propagation, isolation_level=isolation_level)


def _make_decorator(
    *, propagation: Propagation, isolation_level: str | None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """构建事务装饰器（闭包捕获传播级别与隔离级别）。

    :param propagation: 事务传播级别
    :param isolation_level: 会话级隔离级别（环境不支持时忽略）
    :return: 装饰器工厂（接收 fn，返回包裹函数）
    """

    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                db = get_component("db")
                if db is None:
                    raise RuntimeError("@transactional 取不到 db 组件：请先 create_app() 或 bind_components({'db': ...})")
                async with _open_session(db, propagation=propagation, isolation_level=isolation_level):
                    return await fn(*args, **kwargs)

            return _async_wrapper

        @functools.wraps(fn)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            db = get_component("db")
            if db is None:
                raise RuntimeError("@transactional 取不到 db 组件：请先 create_app() 或 bind_components({'db': ...})")
            # 同步函数：无合适异步会话入口，直接执行（框架数据访问均为异步）
            return fn(*args, **kwargs)

        return _sync_wrapper

    return _decorator
