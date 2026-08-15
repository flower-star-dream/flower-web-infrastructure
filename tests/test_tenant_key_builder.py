"""
租户感知缓存 Key 单元测试

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 验证租户维度注入、无租户占位/报错与模板校验（多租户规范 §3）。
"""
import pytest

from web_infra.cache import TenantKeyBuilder
from web_infra.context import RequestContext
from web_infra.error import ParamException


def test_build_injects_tenant_from_context():
    """从请求上下文自动注入租户维度"""
    token = RequestContext.set_tenant_id("tenant-a")
    try:
        key = TenantKeyBuilder.build("web:cache:v1:{tenant_id}:order")
        assert key == "web:cache:v1:tenant-a:order"
    finally:
        RequestContext.clear()
        # 清理 token（clear 已重置上下文）

def test_build_no_tenant_uses_placeholder():
    """无租户上下文时使用 no-tenant 占位"""
    RequestContext.clear()
    key = TenantKeyBuilder.build("web:cache:v1:{tenant_id}:order")
    assert key == "web:cache:v1:no-tenant:order"


def test_build_require_tenant_raises_without_tenant():
    """require_tenant=True 且无租户时抛 ParamException"""
    RequestContext.clear()
    with pytest.raises(ParamException):
        TenantKeyBuilder.build("web:cache:v1:{tenant_id}:order", require_tenant=True)


def test_build_explicit_tenant_overrides_context():
    """显式传入 tenant_id 优先于上下文"""
    token = RequestContext.set_tenant_id("tenant-a")
    try:
        key = TenantKeyBuilder.build("web:cache:v1:{tenant_id}:order", tenant_id="tenant-b")
        assert key == "web:cache:v1:tenant-b:order"
    finally:
        RequestContext.clear()


def test_build_template_must_contain_tenant_placeholder():
    """模板不含 {tenant_id} 抛 ParamException"""
    RequestContext.clear()
    with pytest.raises(ParamException):
        TenantKeyBuilder.build("web:cache:v1:order:{id}", tenant_id="tenant-a")
