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
from typing import TYPE_CHECKING, Any, AsyncIterator

from prometheus_client import Counter

if TYPE_CHECKING:  # 仅静态检查使用，运行时跳过（延迟导入，最小安装不含 SQLAlchemy 时 import 本模块不失败）
    from sqlalchemy.ext.asyncio import AsyncSession

from web_infra.db.database_session_interface import DatabaseSessionInterface
from web_infra.db.mysql_config import MySQLConfig
from web_infra.db.read_write_router import ReadWriteRouter
from web_infra.db.session_scope_mixin import SessionScopeMixin
from web_infra.db.sqlalchemy_database_session import SqlAlchemyDatabaseSession
from web_infra.logging import get_logger

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
    async def orm_session(self, read_replica: bool = False) -> AsyncIterator[AsyncSession]:
        """SQLAlchemy ORM 会话上下文管理器（规范 §10.6：框架统一管理连接生命周期，禁止裸获取连接）。

        进入创建原生 AsyncSession（支持 select(Model) 等 ORM 查询），
        退出自动提交（异常自动回滚）并关闭；业务无需 try/finally。
        read_replica=True 且配置了从库时，读流量路由到从库（规范 S10-2 读写分离）；
        无从库时回退主库并记录 warning。
        """
        if read_replica:
            # 读写分离 S10-2：读流量优先路由从库（轮询），未配置/无可用从库时回退主库并告警
            # 注：getattr 兜底兼容无读写分离能力的配置实现（视为未配置从库）
            if not getattr(self._config, "replica_urls", None):
                logger.warning("mysql_read_replica_not_configured_fallback_to_primary")
                session = await self._config.new_session()
            else:
                replica_name = self._router.next_replica()
                if replica_name is None:
                    logger.warning("mysql_read_replica_not_available_fallback_to_primary")
                    session = await self._config.new_session()
                else:
                    session = await self._config.get_replica_session(name=replica_name)
        else:
            session = await self._config.new_session()
        # 规范 §10.4 长事务监控：进入上下文记录事务开始时间，退出（commit 路径）统计耗时
        started = time.perf_counter()
        try:
            yield session
            await session.commit()
            elapsed = time.perf_counter() - started
            if elapsed >= self._long_transaction_threshold_seconds:
                # 长事务标记+审计（规范 §10.4）：超过阈值仅告警不阻断，
                # 业务长事务走审批流程属业务义务，框架负责审计告警（日志含 datasource 与耗时）
                datasource = getattr(self._config, "datasource_name", "default")
                logger.warning(
                    "mysql_long_transaction datasource=%s duration=%.3fs threshold=%.1fs",
                    datasource, elapsed, self._long_transaction_threshold_seconds,
                )
                _record_long_transaction(datasource)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def close(self) -> None:
        """关闭连接池"""
        await self._config.close()

    async def health_check(self) -> bool:
        """健康检查"""
        return await self._config.health_check()

    def update_pool_metrics(self) -> None:
        """刷新 MySQL 连接池运行指标（代理到配置，供 /metrics 抓取调用）"""
        self._config.update_pool_metrics()
