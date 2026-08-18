"""
租户条件自动注入过滤器

@Author: 花海
@Date: 2026/08/14 18:00
@Description: 数据访问层租户条件统一拦截（多租户规范 §2/§8）：
              SQLAlchemy do_orm_execute 事件为 SELECT/UPDATE/DELETE 自动附加 tenant_id 条件，
              before_flush 为 INSERT 自动填充 tenant_id；业务代码禁止裸拼接租户条件。
              无租户上下文时：strict 模式抛 E2-PERM-000（规范 §2 无上下文拒绝执行），
              兼容模式（默认）返回 no-tenant 占位。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 仅静态检查使用，运行时跳过（延迟导入，最小安装不含 SQLAlchemy 时 import 本模块不失败）
    from sqlalchemy import event

from web_infra.infra.context import RequestContext
from web_infra.capabilities.db.tenant_aware_mixin import TenantAwareMixin
from web_infra.capabilities.db.tenant_guard import NO_TENANT
from web_infra.infra.error import CommonErrorCode


class TenantQueryFilter:
    """租户条件自动注入过滤器（挂载到 session_factory 后对租户模型生效）"""

    def __init__(self, *, strict: bool = False, tenant_column_name: str = "tenant_id") -> None:
        """初始化过滤器。

        :param strict: 强隔离模式：无租户上下文时抛 E2-PERM-000（多租户规范 §2）
        :param tenant_column_name: 租户字段名（默认 tenant_id，全系统统一）
        """
        self._strict = strict
        self._tenant_column_name = tenant_column_name
        self._tenant_models: set[type] = set()

    def register_model(self, model: type) -> "TenantQueryFilter":
        """显式注册租户模型（未继承 TenantAwareMixin 但含 tenant_id 字段的模型使用）"""
        self._tenant_models.add(model)
        return self

    def install(self, session_factory: Any) -> None:
        """将过滤器挂载到 session_factory（同步/异步均可，SQLAlchemy 事件统一触发）"""
        from sqlalchemy import event

        event.listen(session_factory, "do_orm_execute", self._on_orm_execute, propagate=True)
        event.listen(session_factory, "before_flush", self._on_before_flush, propagate=True)

    def require_context(self) -> str:
        """校验租户上下文（strict 模式无租户抛 E2-PERM-000，多租户规范 §2），返回当前租户。

        会话创建入口调用：严格隔离模式下，无租户上下文的数据库访问在创建阶段即被拒绝。
        """
        return self._current_tenant()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _all_tenant_models(self) -> set[type]:
        """全部租户模型 = 显式注册 + TenantAwareMixin 子类"""
        models = set(self._tenant_models)
        models.update(TenantAwareMixin.__subclasses__())
        return models

    def _current_tenant(self) -> str:
        """当前租户：无租户时 strict 抛 E2-PERM-000，否则返回 no-tenant 占位"""
        tid = RequestContext.get_tenant_id()
        if tid:
            return tid
        if self._strict:
            raise CommonErrorCode.PERM_DENIED.to_exception(
                message="无租户上下文，禁止访问租户隔离数据（多租户规范 §2）",
            )
        return NO_TENANT

    def _tenant_column(self, model: type) -> Any | None:
        """取模型租户列（不存在返回 None）"""
        table = getattr(model, "__table__", None)
        if table is None:
            return None
        return table.c.get(self._tenant_column_name)

    def _statement_has_tenant_model(self, stmt: Any) -> bool:
        """SELECT 语句是否查询了租户模型（通过 column_descriptions 的 entity 判断）"""
        descriptions = getattr(stmt, "column_descriptions", None)
        if not descriptions:
            return False
        entities = [d.get("entity") for d in descriptions]
        for entity in entities:
            if isinstance(entity, type):
                for model in self._all_tenant_models():
                    if issubclass(entity, model):
                        return True
        return False

    def _statement_targets_tenant_model(self, stmt: Any) -> bool:
        """UPDATE/DELETE 语句目标表是否为租户模型表（按表名匹配，兼容 ORM 包装语句的表实例差异）"""
        table = getattr(stmt, "table", None)
        if table is None:
            return False
        target_name = getattr(table, "name", None)
        if not target_name:
            return False
        for model in self._all_tenant_models():
            model_table = getattr(model, "__table__", None)
            if model_table is not None and getattr(model_table, "name", None) == target_name:
                return True
        return False

    def _on_orm_execute(self, event_obj: Any) -> None:
        """do_orm_execute：SELECT 附加 where 条件；UPDATE/DELETE 重写语句附加租户条件"""
        if event_obj.is_select:
            if not self._statement_has_tenant_model(event_obj.statement):
                return
            column = self._column_for_statement(event_obj.statement)
            if column is None:
                return
            event_obj.statement = event_obj.statement.where(column == self._current_tenant())
        elif event_obj.is_update or event_obj.is_delete:
            if not self._statement_targets_tenant_model(event_obj.statement):
                return
            column = self._statement_table_column(event_obj.statement)
            if column is None:
                return
            event_obj.statement = event_obj.statement.where(column == self._current_tenant())

    def _column_for_statement(self, stmt: Any) -> Any | None:
        """从 SELECT 语句的实体中取租户列"""
        for entity in [d.get("entity") for d in (getattr(stmt, "column_descriptions", None) or [])]:
            if isinstance(entity, type):
                column = self._tenant_column(entity)
                if column is not None:
                    return column
        return None

    def _statement_table_column(self, stmt: Any) -> Any | None:
        """从 UPDATE/DELETE 目标表取租户列"""
        table = getattr(stmt, "table", None)
        if table is None:
            return None
        return table.c.get(self._tenant_column_name)

    def _on_before_flush(self, session: Any, flush_context: Any, instances: Any) -> None:
        """before_flush：INSERT 自动填充 tenant_id，并校验跨租户写入/删除（多租户规范 §2/§25.3 越权防护）"""
        tenant_id = self._current_tenant()
        # INSERT：空则填充；已有值在 strict 下必须与当前租户一致（禁止业务显式传其他租户 id 跨租户写入）
        for obj in session.new:
            if isinstance(obj, TenantAwareMixin):
                current = getattr(obj, self._tenant_column_name, None)
                if current is None or current == "":
                    setattr(obj, self._tenant_column_name, tenant_id)
                elif self._strict and str(current) != tenant_id:
                    raise CommonErrorCode.PERM_DENIED.to_exception(
                        message=f"跨租户写入禁止: 对象租户 {current} != 当前租户 {tenant_id}（多租户规范 §2）",
                    )
        # 对象级 DELETE（按主键删除，不经过 do_orm_execute）：strict 下校验归属租户，禁止越权删其他租户数据
        for obj in session.deleted:
            if isinstance(obj, TenantAwareMixin):
                current = getattr(obj, self._tenant_column_name, None)
                if self._strict and current is not None and str(current) != tenant_id:
                    raise CommonErrorCode.PERM_DENIED.to_exception(
                        message=f"跨租户删除禁止: 对象租户 {current} != 当前租户 {tenant_id}（多租户规范 §25.3）",
                    )
