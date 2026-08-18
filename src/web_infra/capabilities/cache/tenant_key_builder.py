"""
租户感知缓存 Key 构建器

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 缓存 Key 租户维度注入工具（多租户规范 §3：缓存 Key 必须含租户维度）。
              自动从 RequestContext 取当前租户注入模板 {tenant_id} 占位符；
              无租户上下文时可配置报错（require_tenant=True）或使用 no-tenant 占位。
              规范 T-3（整改 2026-08-15）：租户相关数据缓存必须经本类生成含租户维度的 Key，
              禁止裸用 CacheKeyBuilder 存储租户数据；新增 build_with_tenant 便捷方法，
              业务可直接生成 {prefix}:{tenant_id}:{biz_key} 三段式 Key。
"""
from __future__ import annotations

from web_infra.infra.context import RequestContext
from web_infra.infra.error.param_exception import ParamException

# 无租户时的占位段（避免跨租户串扰，标识该 Key 未绑定租户）
NO_TENANT_PLACEHOLDER = "no-tenant"

_TENANT_PLACEHOLDER = "{tenant_id}"


class TenantKeyBuilder:
    """租户感知缓存 Key 构建器（T-3：租户数据缓存统一入口，禁止裸 CacheKeyBuilder 存租户数据）"""

    @staticmethod
    def build(
        template: str,
        *,
        tenant_id: str | None = None,
        require_tenant: bool = False,
    ) -> str:
        """生成含租户维度的缓存 Key。

        :param template: Key 模板，必须包含 {tenant_id} 占位符（如 "web:common:v1:cache:{tenant_id}:{biz}"）
        :param tenant_id: 显式指定租户（默认从 RequestContext 取当前租户）
        :param require_tenant: 无租户上下文时是否报错（多租户强隔离场景传 True；默认放行用 no-tenant 占位）
        :return: 注入租户后的缓存 Key
        :raises ParamException: 模板不含 {tenant_id}；或 require_tenant=True 且无租户
        """
        if _TENANT_PLACEHOLDER not in template:
            raise ParamException(message=f"租户缓存 Key 模板必须包含 {_TENANT_PLACEHOLDER} 占位符：{template}")

        if tenant_id is None:
            tenant_id = RequestContext.get_tenant_id()
        tenant_id = (tenant_id or "").strip()
        if not tenant_id:
            if require_tenant:
                raise ParamException(message="无租户上下文，禁止生成租户维度缓存 Key（多租户强隔离模式）")
            tenant_id = NO_TENANT_PLACEHOLDER

        return template.replace(_TENANT_PLACEHOLDER, tenant_id)

    @staticmethod
    def build_with_tenant(
        prefix: str,
        tenant_id: str | None,
        biz_key: str,
        *,
        require_tenant: bool = False,
    ) -> str:
        """便捷方法：生成 {prefix}:{tenant_id}:{biz_key} 三段式租户缓存 Key（规范 T-3）。

        适用于业务 Key 结构简单的场景（如 "web:common:v1:order:{tenant_id}:detail:{order_id}" 可拆为
        prefix="web:common:v1:order"、biz_key="detail:{order_id}"），避免业务自行拼模板。

        :param prefix: Key 前缀（业务域静态段，建议含模块与版本，如 web:common:v1:order）
        :param tenant_id: 租户标识（None 时自动取上下文租户，缺省用 no-tenant 占位）
        :param biz_key: 业务键段（含动态段的业务标识，如 detail:1001）
        :param require_tenant: 无租户上下文时是否报错（多租户强隔离场景传 True）
        :return: 注入租户后的缓存 Key
        :raises ParamException: require_tenant=True 且无租户上下文
        """
        template = f"{prefix}:{_TENANT_PLACEHOLDER}:{biz_key}"
        return TenantKeyBuilder.build(template, tenant_id=tenant_id, require_tenant=require_tenant)
