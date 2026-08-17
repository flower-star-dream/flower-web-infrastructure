"""
多数据源管理器

@Author: 花海
@Date: 2026/08/14 22:30
@Description: 多数据源管理器（多租户规范 §4：共享连接池 + 动态路由）：
              持有多个 MySQL 连接（按数据源名），配合 DatabaseRouter 按租户路由；
              未配置路由或目标数据源不存在时快速失败。
              提供 session() 上下文管理器（自动提交/回滚/关闭），业务无需 try/finally。
              整改 T-1（2026-08-15）：数据源切换（route）必须经租户权限校验——当前上下文租户
              与目标租户一致才放行（多租户 §2）；校验可用构造参数 enforce_tenant_check 关闭
              （供测试/内部无上下文路径）。整改 T-4：新增 unregister_tenant 支撑租户删除/归档后
              24h 内路由注销 + 连接释放 + 缓存失效。
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from inspect import isawaitable
from typing import Any, AsyncGenerator

from web_infra.context import RequestContext
from web_infra.db.database_router import DatabaseRouterInterface
from web_infra.db.database_session_interface import DatabaseSessionInterface
from web_infra.error import PermException


class DatabaseManager:
    """多数据源管理器：按名获取连接 / 按租户路由连接（路由须经租户权限校验，T-1）"""

    def __init__(
        self,
        connections: dict[str, Any],
        router: DatabaseRouterInterface | None = None,
        default_name: str = "default",
        *,
        enforce_tenant_check: bool = True,
        cache_invalidator: Callable[[str], Any] | None = None,
    ) -> None:
        """初始化多数据源管理器。

        :param connections: 数据源名 -> 数据库实例（MySQLDatabase 等，需含 close/health_check）
        :param router: 租户路由（可选，未配置时仅支持按名获取）
        :param default_name: 默认数据源名
        :param enforce_tenant_check: T-1 租户权限校验开关（默认开；测试/内部无租户上下文路径可关闭）
        :param cache_invalidator: 租户缓存失效回调（T-4：接收 tenant_id，业务注入删除该租户缓存前缀；
                                  未注入时仅完成路由注销与连接释放，缓存失效由业务自行处理）
        """
        self._connections = connections
        self._router = router
        self._default_name = default_name
        self._enforce_tenant_check = enforce_tenant_check
        self._cache_invalidator = cache_invalidator

    def get(self, name: str | None = None) -> Any:
        """按数据源名获取连接；未配置抛 RuntimeError。

        :param name: 数据源名（默认使用构造时 default_name）
        """
        key = name or self._default_name
        connection = self._connections.get(key)
        if connection is None:
            raise RuntimeError(f"数据源 {key} 未配置")
        return connection

    def _check_tenant_access(self, tenant_id: str) -> None:
        """T-1 租户权限校验：当前上下文租户必须与目标租户一致，否则拒绝数据源切换（多租户 §2）。

        :param tenant_id: 目标租户标识
        :raises PermException: 无租户上下文，或当前上下文租户与目标租户不一致（越权切换）
        """
        if not self._enforce_tenant_check:
            return
        current = (RequestContext.get_tenant_id() or "").strip()
        if not current:
            raise PermException(message="无租户上下文，禁止切换租户数据源（T-1：数据源切换必须经租户权限校验，多租户 §2）")
        if current != tenant_id:
            raise PermException(
                message=f"当前上下文租户 {current} 与目标租户 {tenant_id} 不一致，禁止越权切换数据源（T-1，多租户 §2）"
            )

    def route(self, tenant_id: str, *, enforce_tenant_check: bool | None = None) -> Any:
        """按租户路由获取目标数据源连接（多租户规范 §4 动态路由；T-1 切换前强制租户权限校验）。

        :param tenant_id: 租户标识
        :param enforce_tenant_check: 单次调用覆盖构造开关（None 用构造默认值；内部路径可传 False）
        :return: 目标数据源连接
        :raises PermException: T-1 校验不通过（无租户上下文或与目标租户不一致）
        :raises RuntimeError: 未配置路由或路由目标数据源不存在
        """
        if self._router is None:
            raise RuntimeError("未配置租户数据源路由（DatabaseRouter）")
        check = self._enforce_tenant_check if enforce_tenant_check is None else enforce_tenant_check
        if check:
            self._check_tenant_access(tenant_id)
        name = self._router.route(tenant_id)
        connection = self._connections.get(name)
        if connection is None:
            raise RuntimeError(f"租户 {tenant_id} 路由到未配置的数据源 {name}")
        return connection

    async def unregister_tenant(self, tenant_id: str) -> None:
        """T-4 租户注销：注销路由显式映射 + 释放该租户数据库连接 + 缓存失效。

        由业务在租户删除/归档流程调用（规范 T-4：租户删除/归档后 24h 内路由注销 + 连接释放 + 缓存失效）。
        无显式映射的租户（按模板生成数据源名）：移除映射无效，仅释放连接；
        缓存失效依赖构造注入的 cache_invalidator（如删除 web:*:{tenant_id}:* 前缀）。

        :param tenant_id: 租户标识
        :raises RuntimeError: 未配置租户数据源路由（DatabaseRouter）
        """
        if self._router is None:
            raise RuntimeError("未配置租户数据源路由（DatabaseRouter）")
        # 1. 先解析当前路由目标（unregister 前），关闭并移除该租户数据源连接（模板租户同样适用）
        name = self._router.route(tenant_id)
        connection = self._connections.pop(name, None)
        if connection is not None:
            await connection.close()
        # 2. 注销显式映射（无映射时静默，见 TenantDatabaseRouter.unregister）
        self._router.unregister(tenant_id)
        # 3. 缓存失效（可选注入：业务按租户缓存前缀批量删除；支持同步/异步回调）
        if self._cache_invalidator is not None:
            result = self._cache_invalidator(tenant_id)
            if isawaitable(result):
                await result

    @property
    def names(self) -> list[str]:
        """已配置的数据源名列表"""
        return list(self._connections.keys())

    @property
    def registered_tenants(self) -> list[str]:
        """已注册显式映射的租户列表（T-4 注销审计，代理路由实现）"""
        return list(self._router.registered_tenants()) if self._router is not None else []

    @asynccontextmanager
    async def session(self, name: str | None = None) -> AsyncGenerator[DatabaseSessionInterface, None]:
        """默认数据源会话上下文管理器：进入创建会话，退出自动提交（异常回滚）并关闭。

        :param name: 数据源名（默认使用构造时 default_name）
        """
        async with self.get(name).session() as session:
            yield session

    @asynccontextmanager
    async def orm_session(self, name: str | None = None) -> AsyncGenerator[Any, None]:
        """默认数据源 SQLAlchemy ORM 会话上下文管理器（规范 §10.6：框架统一管理连接生命周期）。

        退出自动提交（异常自动回滚）并关闭；业务无需 try/finally。
        支持实现 orm_session 能力的数据源（如 MySQLDatabase 的原生 AsyncSession）；
        无该能力的数据源（如同步 SQLite）调用时抛 AttributeError。

        :param name: 数据源名（默认使用构造时 default_name）
        """
        async with self.get(name).orm_session() as session:
            yield session

    async def close(self) -> None:
        """关闭全部数据源连接（应用停机时调用）"""
        for connection in self._connections.values():
            await connection.close()

    async def health_check(self) -> bool:
        """探测全部数据源连通性（任一失败返回 False）"""
        for connection in self._connections.values():
            ok = await connection.health_check()
            if not ok:
                return False
        return True
