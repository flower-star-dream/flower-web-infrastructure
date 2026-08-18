"""
租户感知模型 Mixin

@Author: 花海
@Date: 2026/08/14 18:00
@Description: SQLAlchemy 声明式模型的租户感知 Mixin（多租户规范 §2：所有租户相关表必须含 tenant_id
              字段且为联合索引首列）。模型继承本 Mixin 后由 TenantQueryFilter 统一拦截注入租户条件，
              业务代码禁止裸写 `AND tenant_id = ?`（多租户规范 §8 后端红线）。
              整改 T-5（2026-08-15）：补充租户联合索引声明辅助——业务模型通过
              __tenant_compound_indexes__ 声明以 tenant_id 为首列的联合索引列，
              由 __table_args__ 统一生成 Index（见类内说明）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:  # 仅静态检查使用，运行时跳过（延迟导入，最小安装不含 SQLAlchemy 时 import 本模块不失败）
    from sqlalchemy import Index


class TenantAwareMixin:
    """租户感知 Mixin：为模型提供统一的 tenant_id 列（字段类型全系统一致 VARCHAR(64)，禁止 NULL）"""

    # 实例属性注解（运行时仅记录不执行；pyright 下 tenant_id 视为 str）。
    # 注意：不能写 Mapped[str]——SQLAlchemy declarative 需在运行时解析 Mapped 容器类型，
    # 而 Mapped 仅存在于 TYPE_CHECKING 块（运行时不可解析）；实际列由 __init_subclass__ 惰性注入。
    tenant_id: str

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """子类定义时注入 tenant_id 列（延迟导入 SQLAlchemy，避免模块顶层依赖）。

        先注入列再调用 super().__init_subclass__：SQLAlchemy 2.x 的 DeclarativeBase
        在 __init_subclass__ 中立即执行 declarative 映射，映射时需能看到 tenant_id 列。
        """
        if "tenant_id" not in cls.__dict__:
            from sqlalchemy import String
            from sqlalchemy.orm import mapped_column

            setattr(
                cls,
                "tenant_id",
                mapped_column(
                    String(64),
                    nullable=False,
                    index=True,
                    comment="租户标识（多租户规范 §2：联合索引首列，禁止 NULL）",
                ),
            )
        super().__init_subclass__(**kwargs)

    # 租户联合索引声明（规范 T-5：租户相关表索引以 tenant_id 为首列联合索引）。
    # 业务模型在继承本 Mixin 时声明与业务键的联合索引列名列表（首列必须是 tenant_id），
    # 并在模型的 __table_args__ 中引用本类提供的联合索引，示例：
    #   class Order(TenantAwareMixin, Base):
    #       __tablename__ = "orders"
    #       __tenant_compound_indexes__ = [("tenant_id", "biz_id")]   # 声明联合索引列
    #       __table_args__ = (
    #           Index("idx_orders_tenant_id_biz", *Order.__tenant_compound_indexes__[0]),
    #       )
    # 说明：Mixin 无法直接声明引用业务列（如 biz_id）的 Index，故提供声明辅助 + 建索引模板，
    # 由业务模型组合生成；未声明联合索引时保留 tenant_id 单列索引兜底。
    __tenant_compound_indexes__: ClassVar[list[tuple[str, ...]]] = []

    @classmethod
    def tenant_indexes(cls) -> list[Index]:
        """按 __tenant_compound_indexes__ 生成以 tenant_id 为首列的联合索引（规范 T-5）。

        业务模型可在 __table_args__ 中展开使用，避免手工拼接索引名：
            __table_args__ = (*Order.tenant_indexes(),)
        """
        from sqlalchemy import Index

        tablename = getattr(cls, "__tablename__", None)
        if not tablename:
            return []
        return [
            Index(f"idx_{tablename}_tenant_{'_'.join(cols[1:])}", *cols)
            for cols in cls.__tenant_compound_indexes__
        ]
