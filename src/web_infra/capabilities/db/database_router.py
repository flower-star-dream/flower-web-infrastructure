"""
数据库路由接口与租户路由实现

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 多数据源动态路由（多租户规范 §4：独立库/Schema 模式共享连接池 + 动态路由）：
              按租户标识路由到对应数据源；无映射时按统一命名模板生成（如 tenant_{id}）。
              数据源切换须经租户权限校验（§2），由 DatabaseManager.route 统一强制校验（整改 T-1，2026-08-15）。
              整改 T-4（2026-08-15）：新增 unregister/registered_tenants，支撑租户删除/归档后 24h 内
              路由注销（配合 DatabaseManager.unregister_tenant 完成连接释放与缓存失效）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class DatabaseRouterInterface(ABC):
    """数据库路由接口：租户 -> 数据源名"""

    @abstractmethod
    def route(self, tenant_id: str) -> str:
        """按租户标识解析目标数据源名"""
        raise NotImplementedError

    def unregister(self, tenant_id: str) -> None:
        """注销租户的显式映射（多租户规范 T-4：租户删除/归档后路由注销）。

        默认空实现（兼容仅实现 route 的自定义路由）；需显式映射注销的路由实现应覆盖。
        注意：未注册显式映射的租户（按命名模板生成数据源名）无映射可移除，
        其路由注销只能通过移除模板对应的数据源连接完成（见 DatabaseManager.unregister_tenant）。
        """
        del tenant_id  # 默认无显式映射，无需操作

    def registered_tenants(self) -> list[str]:
        """返回已注册显式映射的租户列表（T-4 注销审计/批量治理用）；默认空列表"""
        return []


class TenantDatabaseRouter(DatabaseRouterInterface):
    """租户数据源路由（默认实现）：显式映射优先，未命中按命名模板生成"""

    def __init__(self, mapping: dict[str, str] | None = None, pattern: str = "tenant_{tenant_id}") -> None:
        """初始化租户路由。

        :param mapping: 租户 -> 数据源名 显式映射（优先）
        :param pattern: 未命中时的命名模板（默认 tenant_{tenant_id}，对齐多租户规范 §4 Schema 命名统一模板）
        """
        self._mapping = dict(mapping or {})
        self._pattern = pattern

    def register(self, tenant_id: str, datasource_name: str) -> None:
        """注册租户与数据源的显式映射（可动态维护）"""
        self._mapping[tenant_id] = datasource_name

    def unregister(self, tenant_id: str) -> None:
        """注销租户的显式映射（T-4：租户删除/归档后路由注销，幂等）。

        :param tenant_id: 租户标识；无显式映射时静默返回（按模板生成的租户无映射可移除，
                          需通过 DatabaseManager.unregister_tenant 释放连接完成实际注销）
        """
        self._mapping.pop(tenant_id, None)

    def registered_tenants(self) -> list[str]:
        """返回已注册显式映射的租户列表（T-4 注销审计/租户治理批量排查用）"""
        return list(self._mapping.keys())

    def route(self, tenant_id: str) -> str:
        if tenant_id in self._mapping:
            return self._mapping[tenant_id]
        return self._pattern.format(tenant_id=tenant_id)
