"""
MySQL 通用数据库实现

@Author: 花海
@Date: 2026/08/14 10:00
@Description: MySQL 的通用数据库工厂实现（DatabaseFactoryInterface），基于 MySQLConfig + SQLAlchemy。
              提供两套会话入口（规范 §10.6：统一走框架管理，禁止裸获取连接）：
              - session()：通用 DatabaseSessionInterface（文本 SQL），业务只依赖通用接口，屏蔽 SQLAlchemy 原生 API，
                便于后续替换 PostgreSQL 等其他数据库；
              - orm_session()：SQLAlchemy 原生 AsyncSession（ORM 模型查询 select(Model)），
                同样自动提交/回滚/关闭，业务无需 try/finally；支持读写分离（S10-2）。
              长事务监控（规范 §10.4：事务默认 ≤5s）：orm_session 退出（commit 路径）统计事务耗时，
              超过阈值（long_transaction_threshold_seconds 构造参数，默认 5.0s）记录 warning 审计日志
              （含 datasource 与耗时）并递增 db_long_transaction_total 计数指标；仅告警不阻断，
              业务长事务走审批流程属业务义务，框架做审计告警。
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncGenerator

from prometheus_client import Counter

if TYPE_CHECKING:  # 仅静态检查使用，运行时跳过（延迟导入，最小安装不含 SQLAlchemy 时 import 本模块不失败）
    from sqlalchemy.ext.asyncio import AsyncSession

from web_infra.capabilities.db.database_session_interface import DatabaseSessionInterface
from web_infra.capabilities.db.mysql_config import MySQLConfig
from web_infra.capabilities.db.read_write_router import ReadWriteRouter
from web_infra.capabilities.db.session_scope_mixin import SessionScopeMixin
from web_infra.capabilities.db.sqlalchemy_database_session import SqlAlchemyDatabaseSession
from web_infra.capabilities.db.transaction_propagation import (
    Propagation,
    TransactionFrame,
    TransactionPropagationError,
)
from web_infra.infra.logging import get_logger

logger = get_logger("db.mysql")

try:
    # 长事务计数指标（规范 §10.4 长事务标记+审计；datasource 低基数标签）
    DB_LONG_TRANSACTION_TOTAL = Counter(
        "db_long_transaction_total", "数据库长事务次数（事务耗时超过阈值，仅告警不阻断）", ["datasource"]
    )
except Exception:
    # 指标重复注册等异常不阻断功能（多进程/单测重复导入等场景兜底）
    DB_LONG_TRANSACTION_TOTAL = None


def _record_long_transaction(datasource: str) -> None:
    """长事务审计计数（指标不可用时静默忽略，监控不阻断业务主链路）"""
    if DB_LONG_TRANSACTION_TOTAL is not None:
        DB_LONG_TRANSACTION_TOTAL.labels(datasource).inc()


class MySQLDatabase(SessionScopeMixin):
    """MySQL 的通用数据库工厂实现（DatabaseFactoryInterface）"""

    def __init__(self, config: MySQLConfig, long_transaction_threshold_seconds: float = 5.0) -> None:
        """初始化 MySQL 数据库工厂

        :param config: MySQL 连接配置
        :param long_transaction_threshold_seconds: 长事务判定阈值（规范 §10.4：事务默认 ≤5s）。
            事务耗时超过阈值时记录 warning 审计日志并递增指标，仅告警不阻断；
            业务长事务走审批流程属业务义务，框架做审计告警。
        """
        self._config = config
        self._long_transaction_threshold_seconds = long_transaction_threshold_seconds
        # 多租户租户条件过滤器（由 Application 装配，多租户规范 §2）
        self._tenant_filter: Any | None = None
        # 读写分离路由（规范 S10-2）：从库名为 replica_0..N，由 config 的 replica_urls 数量生成；无从库时路由为空
        # 注：getattr 兜底兼容最小配置替身（如测试中仅提供 new_session 的 FakeConfig，无 datasource_name / replica_names）
        self._router = ReadWriteRouter(primary_name=getattr(config, "datasource_name", "primary"))
        replica_names = getattr(config, "replica_names", None)
        if replica_names is not None:
            self._router.register_replicas(list(replica_names()))

    async def create_session(self) -> DatabaseSessionInterface:
        """创建通用数据库会话（多租户 strict 模式下先校验租户上下文，多租户规范 §2）"""
        if self._tenant_filter is not None:
            self._tenant_filter.require_context()
        session = await self._config.new_session()
        return SqlAlchemyDatabaseSession(session)

    async def _new_session(self, isolation_level: str | None) -> Any:
        """创建原生 AsyncSession（raw，含多租户校验）；会话级隔离级别在事务创建点生效。

        注：MySQL 方言 set_isolation_level 内部会执行一次 COMMIT（SET SESSION 后紧跟 COMMIT，
        见 sqlalchemy/dialects/mysql/base.py:2812），因此会话级隔离级别只能在"新建 owner 事务、
        尚未执行任何 SQL（未触发 autobegin）"时调用；REQUIRED 复用外层时忽略隔离级别（_tx_scope
        的 REQUIRED 分支不调用 new_session），避免把外层已执行操作意外提交。
        """
        wrapper = await self.create_session()  # 复用多租户 strict 校验与包装
        raw = wrapper.native()
        if isolation_level is not None:
            # 会话级隔离级别：仅对当前连接的下一个事务生效，SQLAlchemy 归还连接时经方言复位
            await raw.connection(execution_options={"isolation_level": isolation_level})
        return raw

    def _wrap(self, raw: Any) -> SqlAlchemyDatabaseSession:
        """将原生 AsyncSession 包装为通用会话（复用外层时同样包装，保证文本 SQL 可用）"""
        return SqlAlchemyDatabaseSession(raw)

    async def _begin_savepoint(self, raw: Any) -> Any:
        """开启 SAVEPOINT：SQLAlchemy begin_nested() 返回事务控制对象"""
        return await raw.begin_nested()

    async def _release_savepoint(self, frame: TransactionFrame) -> None:
        """释放 SAVEPOINT（NESTED 正常退出）"""
        await frame.savepoint_tx.commit()

    async def _rollback_savepoint(self, frame: TransactionFrame) -> None:
        """回滚到 SAVEPOINT（NESTED 异常退出）"""
        await frame.savepoint_tx.rollback()

    async def _finalize_commit(self, raw: Any, frame: TransactionFrame) -> None:
        """owner 提交收尾：rollback-only 校验 + 提交 + 长事务审计（规范 §10.4）。

        rollback-only 冲突时不在此处自行回滚，而是抛 TransactionPropagationError，
        由 _tx_scope 的 except 分支统一回滚一次（避免重复 rollback）。
        """
        if frame.rollback_only:
            raise TransactionPropagationError(
                "事务传播冲突：内层事务失败，外层事务已标记 rollback-only，强制回滚"
            )
        await raw.commit()
        elapsed = time.perf_counter() - frame.entered_at
        if elapsed >= self._long_transaction_threshold_seconds:
            datasource = getattr(self._config, "datasource_name", "default")
            logger.warning(
                "mysql_long_transaction datasource=%s duration=%.3fs threshold=%.1fs",
                datasource, elapsed, self._long_transaction_threshold_seconds,
            )
            _record_long_transaction(datasource)

    @property
    def session_factory(self) -> Any:
        """SQLAlchemy 异步会话工厂（async_sessionmaker，供 MysqlOutboxStore 等组件装配；
        引擎未初始化或配置替身缺该属性时返回 None，调用方自行决定兜底）
        """
        return getattr(self._config, "session_factory", None)

    def install_tenant_filter(self, tenant_filter: Any) -> None:
        """装配租户条件过滤器（多租户规范 §2：引擎初始化后自动挂载会话工厂，SQL 自动注入租户条件）"""
        self._tenant_filter = tenant_filter
        self._config.install_tenant_filter(tenant_filter)

    @asynccontextmanager
    async def orm_session(
        self,
        read_replica: bool = False,
        propagation: Propagation = Propagation.REQUIRED,
        isolation_level: str | None = None,
    ) -> AsyncGenerator[AsyncSession, None]:
        """SQLAlchemy ORM 会话上下文管理器（规范 §10.6：框架统一管理连接生命周期，禁止裸获取连接）。

        支持事务传播（propagation）与会话级隔离级别（isolation_level，仅建新事务时生效）；
        进入创建原生 AsyncSession（支持 select(Model) 等 ORM 查询），退出自动提交（异常自动回滚）并关闭；
        业务无需 try/finally。
        read_replica=True 且配置了从库时读流量路由从库（规范 S10-2），无从库回退主库并 warning。
        传播语义与长事务监控由 _tx_scope / _finalize_commit 编排。
        """

        async def _new_orm_session(iso: str | None) -> AsyncSession:
            session = await self._create_orm_session(read_replica)
            if iso is not None:
                await session.connection(execution_options={"isolation_level": iso})
            return session

        async with self._tx_scope(
            propagation=propagation,
            isolation_level=isolation_level,
            new_session=_new_orm_session,
            wrap=lambda raw: raw,  # ORM 入口产出即原生 AsyncSession
        ) as session:
            yield session

    async def _create_orm_session(self, read_replica: bool) -> AsyncSession:
        """创建 ORM 会话（含读写分离路由；无能力回退主库并告警）"""
        if read_replica:
            # 读写分离 S10-2：读流量优先路由从库（轮询），未配置/无可用从库时回退主库并告警
            # 注：getattr 兜底兼容无读写分离能力的配置实现（视为未配置从库）
            if not getattr(self._config, "replica_urls", None):
                logger.warning("mysql_read_replica_not_configured_fallback_to_primary")
                return await self._config.new_session()
            replica_name = self._router.next_replica()
            if replica_name is None:
                logger.warning("mysql_read_replica_not_available_fallback_to_primary")
                return await self._config.new_session()
            return await self._config.get_replica_session(name=replica_name)
        return await self._config.new_session()

    async def close(self) -> None:
        """关闭连接池"""
        await self._config.close()

    async def health_check(self) -> bool:
        """健康检查"""
        return await self._config.health_check()

    def update_pool_metrics(self) -> None:
        """刷新 MySQL 连接池运行指标（代理到配置，供 /metrics 抓取调用）"""
        self._config.update_pool_metrics()
