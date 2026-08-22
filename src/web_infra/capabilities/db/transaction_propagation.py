"""
事务传播与隔离级别

@Author: 花海
@Date: 2026/08/22 10:00
@Description: 事务传播语义（对齐 Spring）：REQUIRED / REQUIRES_NEW / NESTED；
              隔离级别常量（SQLAlchemy 兼容字符串）；
              事务栈（ContextVar，asyncio 场景替代 Spring ThreadLocal）承载传播决策与 rollback-only 标记。
              本模块仅做纯栈管理，与具体数据库无关，供 SessionScopeMixin / SqliteSessionFactory / Outbox 复用。
"""
from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from typing import Any


class Propagation(Enum):
    """事务传播级别（对齐 Spring Propagation 语义）"""

    REQUIRED = "REQUIRED"          # 已有活动事务则复用外层，否则新建
    REQUIRES_NEW = "REQUIRES_NEW"  # 总是新建独立事务（挂起外层）
    NESTED = "NESTED"              # 基于外层事务开启 SAVEPOINT；无外层时等同 REQUIRED


class IsolationLevel:
    """隔离级别常量（SQLAlchemy 兼容字符串，MySQL 语义）。

    DEFAULT（None）：让数据库使用其默认隔离级别（MySQL InnoDB 为 REPEATABLE READ）；
    引擎级 `create_async_engine(isolation_level=...)` 不接收 "DEFAULT" 字符串，故用 None 表示"不注入"。
    """

    DEFAULT = None  # 让数据库使用默认隔离级别（不显式设置）
    READ_UNCOMMITTED = "READ UNCOMMITTED"
    READ_COMMITTED = "READ COMMITTED"
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"


@dataclass
class TransactionFrame:
    """事务栈帧：原生会话 + 传播元信息"""

    session: Any  # 原生会话（MySQL: AsyncSession；SQLite: sqlite3.Connection）
    owner: bool = False  # 是否 commit owner（最外层；owner 负责 commit/rollback/close）
    savepoint: bool = False  # 是否 NESTED 保存点帧
    rollback_only: bool = False  # REQUIRED 内层异常后标记，最外层提交前强制回滚
    savepoint_tx: Any = None  # NESTED 保存点控制对象（AsyncSessionTransaction / SAVEPOINT 名）
    entered_at: float = 0.0  # 事务进入时刻（perf_counter，供长事务监控）


_TX_STACK: ContextVar[tuple[TransactionFrame, ...]] = ContextVar("web_infra_tx_stack", default=())


def current_transaction() -> TransactionFrame | None:
    """当前事务栈顶帧；无活动事务返回 None"""
    stack = _TX_STACK.get()
    return stack[-1] if stack else None


def current_session() -> Any | None:
    """当前事务栈顶原生会话；无活动事务返回 None"""
    frame = current_transaction()
    return frame.session if frame is not None else None


def push_transaction(session: Any, *, owner: bool, savepoint: bool = False, savepoint_tx: Any = None) -> TransactionFrame:
    """压入事务帧并返回（记录进入时刻，供长事务监控）"""
    frame = TransactionFrame(
        session=session,
        owner=owner,
        savepoint=savepoint,
        savepoint_tx=savepoint_tx,
        entered_at=time.perf_counter(),
    )
    _TX_STACK.set(_TX_STACK.get() + (frame,))
    return frame


def pop_transaction() -> TransactionFrame | None:
    """弹出栈顶帧；栈空返回 None"""
    stack = _TX_STACK.get()
    if not stack:
        return None
    _TX_STACK.set(stack[:-1])
    return stack[-1]


def mark_rollback_only() -> None:
    """将最近的 owner 帧标记 rollback-only（REQUIRED 内层异常时调用，强制外层回滚）"""
    stack = _TX_STACK.get()
    for frame in reversed(stack):
        if frame.owner:
            frame.rollback_only = True
            return


class TransactionPropagationError(Exception):
    """事务传播违规：REQUIRED 内层异常导致外层事务 rollback-only，最外层提交前强制回滚并抛出。
    作为框架内部错误处理（全局异常处理器兜底为系统错误），不单独注册错误码。
    """
