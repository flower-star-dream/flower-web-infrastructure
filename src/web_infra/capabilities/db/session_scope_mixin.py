"""
数据库会话生命周期管理 Mixin

@Author: 花海
@Date: 2026/08/14 22:30
@Description: 会话生命周期管理（框架底层处理，业务无需手写 try/finally）：
              `async with factory.session() as session:` 进入自动创建会话，
              退出自动提交（异常自动回滚）并关闭，释放连接。业务代码只写业务逻辑。
              2026/08/22 扩展：支持事务传播（REQUIRED/REQUIRES_NEW/NESTED）与隔离级别，
              跨方法自动共享外层事务（ContextVar 事务栈），并对齐 Spring rollback-only 语义。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from web_infra.capabilities.db.database_session_interface import DatabaseSessionInterface
from web_infra.capabilities.db.transaction_propagation import (
    Propagation,
    TransactionPropagationError,
    current_transaction,
    mark_rollback_only,
    pop_transaction,
    push_transaction,
)


class SessionScopeMixin(ABC):
    """会话生命周期管理 Mixin（提供 session() 异步上下文管理器，支持事务传播）"""

    @abstractmethod
    async def create_session(self) -> DatabaseSessionInterface:
        """创建通用会话（由子类实现）"""

    @asynccontextmanager
    async def session(
        self,
        propagation: Propagation = Propagation.REQUIRED,
        isolation_level: str | None = None,
    ) -> AsyncGenerator[DatabaseSessionInterface, None]:
        """事务作用域会话上下文管理器。

        传播语义（对齐 Spring）：
        - REQUIRED（默认）：已有活动事务则复用外层会话（内层不提交/关闭，由最外层统一提交）；
          内层异常标记外层 rollback-only，最外层提交前强制回滚并抛 TransactionPropagationError。
        - REQUIRES_NEW：新建独立事务（挂起外层），内层提交/回滚互不影响。
        - NESTED：基于外层事务开启 SAVEPOINT；内层异常仅回滚到保存点；无外层时等同 REQUIRED。
        隔离级别仅在建新事务（owner）时生效；复用外层时忽略（避免污染外层连接）。

        用法（业务无需 try/finally）：
            async with db.session() as session:
                rows = await session.query_all(sql, params)
        """
        async with self._tx_scope(
            propagation=propagation,
            isolation_level=isolation_level,
            new_session=self._new_session,
            wrap=self._wrap,
        ) as session:
            yield session

    async def _new_session(self, isolation_level: str | None) -> Any:
        """创建原生会话（raw）；子类可重写以应用隔离级别。默认创建通用会话"""
        return await self.create_session()

    def _wrap(self, raw: Any) -> DatabaseSessionInterface:
        """将原生会话包装为对外产出对象；默认原样返回（子类可重写，如 MySQL 包装 AsyncSession）"""
        if isinstance(raw, DatabaseSessionInterface):
            return raw
        return raw  # type: ignore[return-value]

    async def _finalize_commit(self, raw: Any, frame: Any) -> None:
        """owner 提交路径收尾：先校验 rollback-only，再提交；子类可重写追加监控钩子。

        注意：rollback-only 冲突时不在此处自行回滚，而是抛 TransactionPropagationError，
        由 _tx_scope 的 except 分支统一回滚一次（避免重复 rollback）。
        """
        if frame.rollback_only:
            raise TransactionPropagationError(
                "事务传播冲突：内层事务失败，外层事务已标记 rollback-only，强制回滚"
            )
        await raw.commit()

    async def _rollback(self, raw: Any) -> None:
        """回滚（raw 需支持异步 commit/rollback/close 语义）"""
        await raw.rollback()

    async def _close(self, raw: Any) -> None:
        """关闭会话"""
        await raw.close()

    async def _begin_savepoint(self, raw: Any) -> Any:
        """开启 SAVEPOINT（NESTED 支持）；未实现时抛错"""
        raise TransactionPropagationError("当前数据库实现不支持 NESTED 传播（未实现 begin_savepoint）")

    async def _release_savepoint(self, frame: Any) -> None:
        """释放 SAVEPOINT（NESTED 正常退出）"""
        raise TransactionPropagationError("当前数据库实现不支持 NESTED 传播（未实现 release_savepoint）")

    async def _rollback_savepoint(self, frame: Any) -> None:
        """回滚到 SAVEPOINT（NESTED 异常退出）"""
        raise TransactionPropagationError("当前数据库实现不支持 NESTED 传播（未实现 rollback_savepoint）")

    @asynccontextmanager
    async def _tx_scope(
        self,
        propagation: Propagation,
        isolation_level: str | None,
        new_session: Any,
        wrap: Any,
    ) -> AsyncGenerator[Any, None]:
        """事务传播统一编排：REQUIRED 复用 / NESTED 保存点 / 其余新建 owner 事务"""
        top = current_transaction()

        # REQUIRED：复用外层会话（不提交/关闭，仅弹栈；异常标记外层 rollback-only）
        if top is not None and propagation is Propagation.REQUIRED:
            frame = push_transaction(top.session, owner=False)
            try:
                yield wrap(top.session)
            except Exception:
                mark_rollback_only()
                raise
            finally:
                pop_transaction()
            return

        # NESTED：基于外层会话开 SAVEPOINT（内层异常仅回滚到保存点，不影响外层）
        if top is not None and propagation is Propagation.NESTED:
            savepoint_tx = await self._begin_savepoint(top.session)
            frame = push_transaction(top.session, owner=False, savepoint=True, savepoint_tx=savepoint_tx)
            try:
                yield wrap(top.session)
            except Exception:
                await self._rollback_savepoint(frame)
                raise
            else:
                await self._release_savepoint(frame)
            finally:
                pop_transaction()
            return

        # 无外层（REQUIRED/NESTED 退化）或 REQUIRES_NEW：新建 owner 事务
        raw = await new_session(isolation_level)
        frame = push_transaction(raw, owner=True)
        try:
            yield wrap(raw)
            await self._finalize_commit(raw, frame)
        except Exception:
            await self._rollback(raw)
            raise
        finally:
            await self._close(raw)
            pop_transaction()
