"""
租户治理整改测试（T-1 切换校验 / T-4 租户注销 / T-5 联合索引声明）

@Author: 花海
@Date: 2026/08/15
@Description: 验证：
              - T-1：数据源切换必须经租户权限校验——无租户上下文拒绝、上下文租户与目标不一致拒绝、
                     一致放行；enforce_tenant_check 开关可关闭（多租户 §2）。
              - T-4：TenantDatabaseRouter.unregister/registered_tenants 与
                     DatabaseManager.unregister_tenant（路由注销 + 连接释放 + 缓存失效回调）。
              - T-5：TenantAwareMixin 提供以 tenant_id 为首列的联合索引声明辅助。
"""
import pytest
from sqlalchemy import Index, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from web_infra.context import RequestContext
from web_infra.db import DatabaseManager, TenantAwareMixin, TenantDatabaseRouter
from web_infra.error import PermException


class _FakeDatabase:
    """模拟数据库连接（close/health_check）"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def health_check(self) -> bool:
        return True


def _manager(**kwargs) -> DatabaseManager:
    """构造带路由与 fake 连接的管理器（默认 T-1 校验开启）"""
    connections = {
        "tenant_a": _FakeDatabase("tenant_a"),
        "tenant_b": _FakeDatabase("tenant_b"),
    }
    router = TenantDatabaseRouter(mapping={"vip-a": "tenant_a"}, pattern="{tenant_id}")
    return DatabaseManager(connections, router=router, **kwargs)


# ------------------------------------------------------------------
# T-1 数据源切换租户权限校验
# ------------------------------------------------------------------

def test_route_denied_without_tenant_context():
    """无租户上下文：切换数据源抛 PermException（T-1，多租户 §2）"""
    RequestContext.clear()
    manager = _manager()
    with pytest.raises(PermException):
        manager.route("tenant_a")


def test_route_denied_when_context_tenant_mismatch():
    """上下文租户与目标租户不一致：拒绝越权切换（T-1）"""
    RequestContext.set_tenant_id("tenant_b")
    try:
        manager = _manager()
        with pytest.raises(PermException):
            manager.route("tenant_a")
    finally:
        RequestContext.clear()


def test_route_allowed_when_context_tenant_matches():
    """上下文租户与目标租户一致：放行（T-1）"""
    RequestContext.set_tenant_id("tenant_a")
    try:
        manager = _manager()
        assert manager.route("tenant_a").name == "tenant_a"
    finally:
        RequestContext.clear()


def test_route_with_check_disabled():
    """enforce_tenant_check=False（构造开关）：无上下文也放行（测试/内部路径）"""
    RequestContext.clear()
    manager = _manager(enforce_tenant_check=False)
    assert manager.route("tenant_b").name == "tenant_b"


def test_route_per_call_check_override():
    """单次调用 enforce_tenant_check=False 覆盖构造默认开启的校验"""
    RequestContext.clear()
    manager = _manager()
    with pytest.raises(PermException):
        manager.route("tenant_b")
    # 单次调用显式关闭校验（内部无上下文路径）
    assert manager.route("tenant_b", enforce_tenant_check=False).name == "tenant_b"


def test_route_unconfigured_target_still_fails():
    """校验通过但路由目标数据源不存在：仍抛 RuntimeError（快速失败语义不变）"""
    RequestContext.set_tenant_id("9999")
    try:
        manager = _manager()
        with pytest.raises(RuntimeError):
            manager.route("9999")
    finally:
        RequestContext.clear()


# ------------------------------------------------------------------
# T-4 租户注销（路由 + 连接 + 缓存）
# ------------------------------------------------------------------

def test_router_unregister_removes_explicit_mapping():
    """unregister 移除显式映射；模板租户无映射可移除（幂等静默）"""
    router = TenantDatabaseRouter(mapping={"vip-a": "tenant_a"}, pattern="tenant_{tenant_id}")
    assert router.route("vip-a") == "tenant_a"
    router.unregister("vip-a")
    assert router.route("vip-a") == "tenant_vip-a"  # 退回模板
    router.unregister("vip-a")  # 再次注销不抛错
    router.unregister("never-registered")  # 未注册的模板租户静默


def test_router_registered_tenants():
    """registered_tenants 返回显式映射租户列表（T-4 注销审计）"""
    router = TenantDatabaseRouter()
    assert router.registered_tenants() == []
    router.register("t1", "db-1")
    router.register("t2", "db-2")
    assert sorted(router.registered_tenants()) == ["t1", "t2"]


@pytest.mark.asyncio
async def test_manager_unregister_tenant_releases_connection_and_mapping():
    """unregister_tenant：释放该租户连接 + 注销映射 + 连接不再可路由（T-4）"""
    manager = _manager()
    await manager.unregister_tenant("vip-a")
    # 连接已关闭并移除
    assert "tenant_a" not in manager.names
    # 显式映射已注销（退回模板名，但模板对应连接未配置）
    with pytest.raises(RuntimeError):
        manager.route("vip-a", enforce_tenant_check=False)


@pytest.mark.asyncio
async def test_manager_unregister_tenant_template_tenant():
    """模板租户（无显式映射）：unregister_tenant 释放连接、映射注销静默（T-4）"""
    RequestContext.set_tenant_id("tenant_b")
    try:
        manager = _manager()
        await manager.unregister_tenant("tenant_b")
        assert "tenant_b" not in manager.names
    finally:
        RequestContext.clear()


@pytest.mark.asyncio
async def test_manager_unregister_tenant_invalidates_cache():
    """注入 cache_invalidator：注销时按 tenant_id 触发缓存失效（T-4）"""
    invalidated: list[str] = []

    async def invalidator(tenant_id: str) -> None:
        invalidated.append(tenant_id)

    manager = _manager(cache_invalidator=invalidator)
    await manager.unregister_tenant("vip-a")
    assert invalidated == ["vip-a"]


@pytest.mark.asyncio
async def test_manager_unregister_tenant_without_router():
    """未配置路由时 unregister_tenant 抛 RuntimeError"""
    manager = DatabaseManager({"default": _FakeDatabase("default")})
    with pytest.raises(RuntimeError):
        await manager.unregister_tenant("t1")


def test_manager_registered_tenants_proxy():
    """DatabaseManager.registered_tenants 代理路由的显式映射租户（T-4 审计）"""
    manager = _manager()
    assert sorted(manager.registered_tenants) == ["vip-a"]
    assert DatabaseManager({"default": _FakeDatabase("default")}).registered_tenants == []


# ------------------------------------------------------------------
# T-5 租户联合索引声明
# ------------------------------------------------------------------

class _Base(DeclarativeBase):
    """测试 ORM 基类"""


class _Order(TenantAwareMixin, _Base):
    """继承 Mixin 的租户模型（演示 T-5 联合索引声明）"""

    __tablename__ = "orders"
    __tenant_compound_indexes__ = [("tenant_id", "biz_id"), ("tenant_id", "created_at")]

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    biz_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(32))


def test_tenant_mixin_compound_indexes_declared():
    """Mixin 提供 __tenant_compound_indexes__ 声明属性（默认空列表，T-5）"""
    assert TenantAwareMixin.__tenant_compound_indexes__ == []


def test_tenant_indexes_generate_compound_indexes():
    """tenant_indexes() 按声明生成以 tenant_id 为首列的联合索引（T-5）"""
    indexes = _Order.tenant_indexes()
    assert len(indexes) == 2
    for index in indexes:
        assert isinstance(index, Index)
        # 首列必须为 tenant_id（字符串列名经 Index.expressions 暴露）
        assert list(index.expressions)[0] == "tenant_id"
        assert index.name and index.name.startswith("idx_orders_tenant_")
    names = {index.name for index in indexes}
    assert names == {"idx_orders_tenant_biz_id", "idx_orders_tenant_created_at"}


def test_tenant_mixin_single_column_index_remains():
    """未声明联合索引时保留 tenant_id 单列索引兜底（向后兼容）"""
    assert TenantAwareMixin.__tenant_compound_indexes__ == []
    # 模型表上 tenant_id 仍为 index=True（单列索引兜底，T-5 未声明联合索引时的保底）
    assert _Order.__table__.columns["tenant_id"].index is True
