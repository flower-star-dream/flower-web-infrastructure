"""
通用数据库工厂接口

@Author: 花海
@Date: 2026/08/14 22:30
@Description: 通用数据库工厂接口（SPI 扩展点），遵循规范 §3 与 §10。
              用户扩展其他数据库时，实现本接口即可接入框架：
              - create_session：创建通用会话
              - session：异步上下文管理器（推荐用法，自动提交/回滚/关闭，业务无需 try/finally）
              - close：释放连接池/底层资源
              - health_check：健康检查
"""
from __future__ import annotations

from typing import AsyncContextManager, Protocol, runtime_checkable

from web_infra.db.database_session_interface import DatabaseSessionInterface


@runtime_checkable
class DatabaseFactoryInterface(Protocol):
    """通用数据库工厂接口（SPI 扩展点）"""

    async def create_session(self) -> DatabaseSessionInterface:
        """创建通用数据库会话"""
        ...

    def session(self) -> AsyncContextManager[DatabaseSessionInterface]:
        """异步上下文管理器：进入创建会话，退出自动提交（异常回滚）并关闭（业务无需 try/finally）"""
        ...

    async def close(self) -> None:
        """关闭连接池/底层资源"""
        ...

    async def health_check(self) -> bool:
        """健康检查"""
        ...
