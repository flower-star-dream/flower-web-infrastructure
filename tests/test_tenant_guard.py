"""
租户上下文校验守卫单元测试

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 验证无租户拒绝执行、兼容模式占位与显式租户（多租户规范 §2）。
"""
import pytest

from web_infra.context import RequestContext
from web_infra.db import TenantGuard
from web_infra.error import BizException


def test_require_tenant_with_context():
    """有租户上下文时返回租户标识"""
    RequestContext.set_tenant_id("tenant-a")
    try:
        assert TenantGuard.require_tenant() == "tenant-a"
    finally:
        RequestContext.clear()


def test_require_tenant_strict_raises_without_tenant():
    """strict=True 且无租户时抛 BizException（E2-PERM）"""
    RequestContext.clear()
    with pytest.raises(BizException) as exc_info:
        TenantGuard.require_tenant(strict=True)
    assert exc_info.value.code == "E2-PERM-000"


def test_require_tenant_non_strict_placeholder():
    """非 strict 且无租户时返回 no-tenant 占位"""
    RequestContext.clear()
    assert TenantGuard.require_tenant() == "no-tenant"


def test_current_tenant_placeholder():
    """current_tenant 无租户返回 no-tenant"""
    RequestContext.clear()
    assert TenantGuard.current_tenant() == "no-tenant"


def test_require_tenant_explicit():
    """显式传入租户优先"""
    RequestContext.clear()
    assert TenantGuard.require_tenant(tenant_id="tenant-x") == "tenant-x"
