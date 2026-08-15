"""
租户数据访问拦截单元测试

@Author: 花海
@Date: 2026/08/14 18:00
@Description: 验证 SQLAlchemy 事件自动注入 tenant_id：INSERT 填充、SELECT/UPDATE/DELETE 过滤、
              无租户 strict 拒绝、非租户模型不拦截（多租户规范 §2/§8）。
"""
import pytest
from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from web_infra.context import RequestContext
from web_infra.db import TenantAwareMixin, TenantQueryFilter
from web_infra.error import BizException


class Base(DeclarativeBase):
    """测试基类"""


class Order(TenantAwareMixin, Base):
    """租户模型（继承 TenantAwareMixin）"""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))


class Product(Base):
    """非租户模型（不继承 TenantAwareMixin）"""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))


@pytest.fixture()
def session_factory():
    """内存 sqlite + 挂载租户过滤器"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    TenantQueryFilter().install(factory)
    RequestContext.clear()
    yield factory
    RequestContext.clear()
    engine.dispose()


def _add_order(factory, tenant: str, name: str) -> None:
    """在指定租户上下文下新增订单（验证 INSERT 自动填充）"""
    RequestContext.set_tenant_id(tenant)
    with factory() as session:
        session.add(Order(name=name))
        session.commit()


def test_insert_auto_fills_tenant_id(session_factory):
    """INSERT 自动填充 tenant_id（业务未显式设置）"""
    _add_order(session_factory, "t1", "order-1")
    RequestContext.set_tenant_id("t1")
    with session_factory() as session:
        row = session.execute(select(Order)).scalar_one()
        assert row.tenant_id == "t1"


def test_select_auto_filters_by_tenant(session_factory):
    """SELECT 自动附加租户条件：t1 查不到 t2 的数据"""
    _add_order(session_factory, "t1", "order-1")
    _add_order(session_factory, "t2", "order-2")

    RequestContext.set_tenant_id("t1")
    with session_factory() as session:
        rows = session.execute(select(Order)).scalars().all()
        assert [r.name for r in rows] == ["order-1"]

    RequestContext.set_tenant_id("t2")
    with session_factory() as session:
        rows = session.execute(select(Order)).scalars().all()
        assert [r.name for r in rows] == ["order-2"]


def test_non_tenant_model_not_filtered(session_factory):
    """非租户模型不拦截（全量可见）"""
    with session_factory() as session:
        session.add(Product(name="p1"))
        session.add(Product(name="p2"))
        session.commit()
    RequestContext.set_tenant_id("t1")
    with session_factory() as session:
        rows = session.execute(select(Product)).scalars().all()
        assert len(rows) == 2


def test_strict_mode_rejects_without_tenant():
    """strict 模式无租户上下文拒绝执行（E2-PERM-000）"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    TenantQueryFilter(strict=True).install(factory)
    RequestContext.clear()
    try:
        with factory() as session:
            with pytest.raises(BizException) as exc_info:
                session.execute(select(Order)).scalars().all()
            assert exc_info.value.code == "E2-PERM-000"
    finally:
        RequestContext.clear()
        engine.dispose()


def test_update_auto_scoped_by_tenant(session_factory):
    """UPDATE 自动附加租户条件：仅更新当前租户数据"""
    _add_order(session_factory, "t1", "order-1")
    _add_order(session_factory, "t2", "order-2")

    RequestContext.set_tenant_id("t1")
    from sqlalchemy import update

    with session_factory() as session:
        session.execute(update(Order).where(Order.name == "order-1").values(name="order-1-updated"))
        session.commit()

    RequestContext.set_tenant_id("t2")
    with session_factory() as session:
        row = session.execute(select(Order)).scalar_one()
        assert row.name == "order-2"  # t2 数据未被 t1 的更新波及


def test_delete_auto_scoped_by_tenant(session_factory):
    """DELETE 自动附加租户条件：仅删除当前租户数据"""
    _add_order(session_factory, "t1", "order-1")
    _add_order(session_factory, "t2", "order-2")

    RequestContext.set_tenant_id("t1")
    from sqlalchemy import delete

    with session_factory() as session:
        session.execute(delete(Order))
        session.commit()

    RequestContext.set_tenant_id("t2")
    with session_factory() as session:
        rows = session.execute(select(Order)).scalars().all()
        assert [r.name for r in rows] == ["order-2"]
