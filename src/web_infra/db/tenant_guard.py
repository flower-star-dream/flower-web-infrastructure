"""
租户上下文校验守卫

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 数据访问层租户上下文校验（多租户规范 §2：无租户上下文时拒绝执行数据库操作）。
              强隔离模式（app.tenant.strict=true）下无租户抛 E2-PERM-000；兼容模式返回 no-tenant。
              数据源切换需经租户校验（§2 租户切换必须经权限校验）通过 require_tenant 一并保障。
"""
from __future__ import annotations

from web_infra.context import RequestContext
from web_infra.error import BizException, CommonErrorCode

# 无租户占位（兼容单体/非租户场景，配合 strict 开关使用）
NO_TENANT = "no-tenant"


class TenantGuard:
    """租户上下文校验守卫"""

    @staticmethod
    def current_tenant() -> str:
        """返回当前租户（无租户返回 no-tenant 占位，不抛错）"""
        return RequestContext.get_tenant_id() or NO_TENANT

    @staticmethod
    def require_tenant(*, tenant_id: str | None = None, strict: bool = False) -> str:
        """获取并校验当前租户。

        :param tenant_id: 显式指定租户（默认从请求上下文读取）
        :param strict: 强隔离模式：无租户抛 E2-PERM-000（多租户规范 §2）；False 时返回 no-tenant 占位
        :return: 租户标识（有效时）；无租户且非 strict 返回 NO_TENANT
        :raises BizException: strict=True 且无租户上下文
        """
        tid = tenant_id or RequestContext.get_tenant_id()
        tid = (tid or "").strip()
        if tid:
            return tid
        if strict:
            raise BizException(
                CommonErrorCode.PERM_DENIED,
                message="无租户上下文，禁止执行租户隔离数据访问（多租户规范 §2）",
            )
        return NO_TENANT
