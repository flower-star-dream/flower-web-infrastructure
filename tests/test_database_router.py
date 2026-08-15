"""
多数据源路由单元测试

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 验证租户路由规则、显式映射注册、无路由/无目标数据源快速失败（多租户规范 §4）。
              整改 T-1（2026-08-15）：route 默认强制租户权限校验，用例需设置 RequestContext 租户上下文；
              切换校验的拒绝/放行行为详见 tests/test_tenant_governance.py。
"""
import pytest

from web_infra.context import RequestContext
from web_infra.db import DatabaseManager, TenantDatabaseRouter


class _FakeDatabase:
    """模拟数据库连接（close/health_check）"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def health_check(self) -> bool:
        return True


def test_tenant_router_pattern():
    """未命中映射时按命名模板生成数据源名"""
    router = TenantDatabaseRouter(pattern="tenant_{tenant_id}")
    assert router.route("1001") == "tenant_1001"


def test_tenant_router_mapping_priority():
    """显式映射优先于模板"""
    router = TenantDatabaseRouter(mapping={"vip": "main-db"}, pattern="tenant_{tenant_id}")
    assert router.route("vip") == "main-db"
    assert router.route("1002") == "tenant_1002"


def test_tenant_router_register():
    """动态注册租户映射"""
    router = TenantDatabaseRouter()
    router.register("1001", "db-east")
    assert router.route("1001") == "db-east"


@pytest.mark.asyncio
async def test_database_manager_get_by_name():
    """按名获取连接，未配置抛 RuntimeError"""
    manager = DatabaseManager({"default": _FakeDatabase("default")}, default_name="default")
    assert manager.get("default").name == "default"
    with pytest.raises(RuntimeError):
        manager.get("missing")


@pytest.mark.asyncio
async def test_database_manager_route_by_tenant():
    """按租户路由获取目标数据源（T-1：上下文租户一致才放行）"""
    manager = DatabaseManager(
        {"tenant_1001": _FakeDatabase("tenant_1001")},
        router=TenantDatabaseRouter(pattern="tenant_{tenant_id}"),
    )
    RequestContext.set_tenant_id("1001")
    try:
        assert manager.route("1001").name == "tenant_1001"
    finally:
        RequestContext.clear()


@pytest.mark.asyncio
async def test_database_manager_route_without_router_fails():
    """未配置路由时 route 抛 RuntimeError"""
    manager = DatabaseManager({"default": _FakeDatabase("default")})
    with pytest.raises(RuntimeError):
        manager.route("1001")


@pytest.mark.asyncio
async def test_database_manager_route_unconfigured_target_fails():
    """路由目标数据源不存在抛 RuntimeError（T-1 校验通过后仍快速失败）"""
    manager = DatabaseManager(
        {"tenant_1": _FakeDatabase("tenant_1")},
        router=TenantDatabaseRouter(pattern="tenant_{tenant_id}"),
    )
    RequestContext.set_tenant_id("9999")
    try:
        with pytest.raises(RuntimeError):
            manager.route("9999")
    finally:
        RequestContext.clear()


@pytest.mark.asyncio
async def test_database_manager_close_and_health():
    """close 关闭全部连接、health_check 全绿"""
    db = _FakeDatabase("default")
    manager = DatabaseManager({"default": db})
    assert await manager.health_check() is True
    await manager.close()
    assert db.closed is True
