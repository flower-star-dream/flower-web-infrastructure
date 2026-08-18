"""
权限守卫（RBAC 声明式控制）

@Author: 花海
@Date: 2026/08/14 20:00
@Description: 接口级权限校验（规范 §6.6 声明式控制 + §25.3 越权防护：后端必须按角色/权限点校验）。
              FastAPI 依赖注入方式使用：`Depends(PermissionGuard.require(AuthConstant.AUTH_PERM_ORDER_WRITE))`。
              权限来源为 AuthMiddleware 注入请求上下文的 scope（空格分隔的权限列表），admin 通配。
              权限点必须走常量（§6.6 禁止裸字符串），校验失败统一抛 E2-PERM-000（403）。
"""
from __future__ import annotations

from typing import Any, Callable

from web_infra.infra.constants.auth_constant import AuthConstant
from web_infra.infra.context import RequestContext
from web_infra.infra.error import CommonErrorCode


class PermissionGuard:
    """接口级权限守卫（声明式权限控制，规范 §6.6）"""

    @staticmethod
    def require(*permissions: str) -> Callable[[], None]:
        """声明式权限依赖：要求当前请求上下文具备全部指定权限点。

        :param permissions: 权限点（走 AuthConstant.AUTH_PERM_* 常量，禁止裸字符串）
        :return: FastAPI 依赖函数（无权限抛 E2-PERM-000）
        """
        if any(not isinstance(p, str) or not p for p in permissions):
            raise ValueError("权限点必须为非空字符串常量（AuthConstant.AUTH_PERM_*）")

        def _dependency() -> None:
            scope = RequestContext.get_scope()
            granted = set(scope.split()) if scope else set()
            if AuthConstant.AUTH_SCOPE_ADMIN in granted:
                return  # 超级管理员通配（§6.6 Scope 最小化：admin 仅超级管理员）
            missing = set(permissions) - granted
            if missing:
                raise CommonErrorCode.PERM_DENIED.to_exception(
                    message=f"缺少权限: {', '.join(sorted(missing))}",
                )

        return _dependency
