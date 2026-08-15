"""
MySQL 数据库配置

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 基于 SQLAlchemy 2.x + aiomysql 的 MySQL 异步数据库配置，遵循规范 §10（数据访问）与 §14.1（连接池）。
              支持连接池、超时、回收、慢 SQL 分级告警（§18.5.3）与连接泄漏检测（§10.6）。
              引擎延迟初始化，避免模块导入时立即建连；通过 asyncio.Lock 保护并发初始化。
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING, Any, AsyncIterator
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

if TYPE_CHECKING:  # 仅静态检查使用，运行时跳过（延迟导入，最小安装不含 SQLAlchemy 时 import 本模块不失败）
    from sqlalchemy import event, text
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

# 引擎工厂占位：模块顶层不导入 SQLAlchemy（延迟导入），实际实现由引擎创建方法在调用时解析；
# 模块属性保持存在以兼容测试 monkeypatch 覆盖（历史约定，见 _do_create_engine 说明）
create_async_engine: Any = None

from web_infra.constants import INFRA_MYSQL_INIT_COMMAND, INFRA_TRUE_VALUES
from web_infra.db.mysql_connection_settings import MySQLConnectionSettings
from web_infra.db.read_write_router import ReadWriteRouter
from web_infra.logging import get_logger
from web_infra.monitoring.metrics import MYSQL_POOL_CONNECTION_LEAK_TOTAL, record_slow_sql
from web_infra.monitoring.pool_metrics import record_mysql_pool_metrics

logger = get_logger("db.mysql")


def _sql_preview(statement: Any) -> str:
    """慢 SQL 摘要（脱敏）：仅保留语句骨架，去除引号包裹的字面量，参数绑定值绝不进入日志/指标"""
    raw = " ".join(str(statement).split())
    sanitized = re.sub(r"'[^']*'|\"[^\"]*\"", "?", raw)
    return sanitized[:200]


class _AsyncSessionContextManager:
    """异步会话上下文管理器：进入时懒加载引擎并返回 AsyncSession"""

    def __init__(self, config: "MySQLConfig") -> None:
        self._config = config
        self._session_cm: Any = None

    async def __aenter__(self) -> AsyncSession:
        await self._config._ensure_engine()
        self._session_cm = self._config.session_factory()  # type: ignore[union-attr]
        return await self._session_cm.__aenter__()

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._session_cm is not None:
            await self._session_cm.__aexit__(exc_type, exc_val, exc_tb)


class MySQLConfig:
    """MySQL 数据库配置：管理异步引擎与会话工厂生命周期，支持延迟初始化"""

    def __init__(
        self,
        url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        settings: MySQLConnectionSettings | None = None,
        pool_size: int = 8,
        max_overflow: int = 8,
        pool_recycle: int = 1800,
        pool_timeout: int = 8,
        echo: bool = False,
        pool_pre_ping: bool = True,
        connect_timeout: int = 10,
        read_timeout: int = 30,
        write_timeout: int = 30,
        datasource_name: str = "default",
        slow_sql_threshold_seconds: float = 0.2,
        slow_sql_critical_seconds: float = 2.0,
        leak_detection_threshold_seconds: float = 10.0,
        replica_urls: list[str] | None = None,
        replica_username: str | None = None,
        replica_password: str | None = None,
    ) -> None:
        """初始化 MySQL 配置（仅保存参数，不立即建连）"""
        if settings is not None:
            self.settings = settings
            self.url = settings.to_sqlalchemy_url()
            self.connect_args = settings.to_connect_args()
            self.username = settings.username
            self.password = settings.password
            pool_pre_ping = getattr(settings, "pool_pre_ping", pool_pre_ping)
            slow_sql_threshold_seconds = getattr(settings, "slow_sql_threshold_seconds", slow_sql_threshold_seconds)
            slow_sql_critical_seconds = getattr(settings, "slow_sql_critical_seconds", slow_sql_critical_seconds)
            leak_detection_threshold_seconds = getattr(
                settings, "leak_detection_threshold_seconds", leak_detection_threshold_seconds
            )
        elif url is not None:
            self.url, self.connect_args = self._build_url(url, username, password)
            self.connect_args["connect_timeout"] = connect_timeout
            # 读写超时默认 30s（规范 §14.1 三层超时），URL 未显式声明时生效
            self.connect_args.setdefault("read_timeout", read_timeout)
            self.connect_args.setdefault("write_timeout", write_timeout)
            self.username = username
            self.password = password
        else:
            raise ValueError("必须提供 url 或 settings 之一")

        self.pool_size = pool_size
        self.max_overflow = max_overflow
        # 空闲回收（S14-3）：连接空闲超过 pool_recycle 秒后归还时强制重建，防止 MySQL wait_timeout 断连
        self.pool_recycle = pool_recycle
        self.pool_timeout = pool_timeout
        self.echo = echo
        self.pool_pre_ping = pool_pre_ping
        # 池名（S14-3）：datasource_name 即连接池业务名，用于日志/指标低基数标签（慢 SQL/池指标/泄漏），
        # 业务应配置有意义的 datasource_name（如 order-db / user-db），便于监控按池定位
        self.datasource_name = datasource_name
        self.slow_sql_threshold_seconds = slow_sql_threshold_seconds
        self.slow_sql_critical_seconds = slow_sql_critical_seconds
        self.leak_detection_threshold_seconds = leak_detection_threshold_seconds
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None
        # 多租户租户条件过滤器（多租户规范 §2：引擎初始化后自动挂载到 session_factory）
        self._tenant_filter: Any = None
        # asyncio.Lock 保护协程切换下的并发初始化
        self._lock = asyncio.Lock()
        # 读写分离（规范 S10-2）：从库 URL 列表与账号（缺省复用主库账号），引擎懒加载
        self.replica_urls: list[str] = list(replica_urls or [])
        self.replica_username = replica_username
        self.replica_password = replica_password
        self._replica_engines: dict[str, AsyncEngine] = {}
        self._replica_session_factories: dict[str, async_sessionmaker[AsyncSession]] = {}
        # 从库轮询路由（仅名称路由，线程安全）；从库名为 replica_0..N
        self._replica_router = ReadWriteRouter(primary_name=datasource_name)
        self._replica_router.register_replicas(self.replica_names())

    def install_tenant_filter(self, tenant_filter: Any) -> None:
        """注册租户条件过滤器：引擎初始化后自动挂载到 session_factory（多租户规范 §2）。

        在引擎已初始化（session_factory 存在）时立即挂载；否则延迟到 _do_create_engine 完成时挂载。
        """
        self._tenant_filter = tenant_filter
        if self.session_factory is not None:
            tenant_filter.install(self.session_factory)

    @staticmethod
    def _build_url(url: str, username: str | None, password: str | None) -> tuple[str, dict[str, Any]]:
        """注入用户名/密码，并将 JDBC 风格查询参数转换为 aiomysql 合法参数"""
        parsed = urlparse(url)
        query_params = dict(parse_qsl(parsed.query))

        aiomysql_supported = {
            "charset", "sql_mode", "read_default_file", "conv", "use_unicode", "client_flag",
            "cursorclass", "init_command", "connect_timeout", "read_default_group", "autocommit",
            "local_infile", "max_allowed_packet", "auth_plugin_map", "read_timeout", "write_timeout",
            "bind_address", "binary_prefix", "program_name", "server_public_key", "ssl", "db",
        }
        jdbc_to_aiomysql = {
            "characterencoding": "charset",
            "allowpublickeyretrieval": None,
            "servertimezone": None,
            "useunicode": None,
        }

        # 安全默认：URL 未声明 usessl 时默认开启 SSL（与 MySQLConnectionSettings 默认一致，规范 §10）
        use_ssl = True
        converted: dict[str, str] = {}
        connect_args: dict[str, Any] = {"init_command": INFRA_MYSQL_INIT_COMMAND}
        for key, value in query_params.items():
            lower_key = key.lower()
            if lower_key == "allowpublickeyretrieval":
                connect_args["server_public_key"] = value.lower() in INFRA_TRUE_VALUES
                continue
            if lower_key == "usessl":
                use_ssl = value.lower() in INFRA_TRUE_VALUES
                continue
            if lower_key in jdbc_to_aiomysql:
                mapped_key = jdbc_to_aiomysql[lower_key]
                if mapped_key is None:
                    continue
                converted[mapped_key] = value
            elif lower_key in aiomysql_supported:
                converted[key] = value

        if use_ssl:
            connect_args["ssl"] = {"ca": None, "check_hostname": True}

        if "charset" in converted and converted["charset"].lower() == "utf8":
            converted["charset"] = "utf8mb4"

        new_query = urlencode(converted)
        parsed = parsed._replace(query=new_query)

        if not username:
            return urlunparse(parsed), connect_args

        userinfo = username
        if password:
            userinfo += f":{password}"
        netloc = f"{userinfo}@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"
        return urlunparse(parsed._replace(netloc=netloc)), connect_args

    async def _ensure_engine(self) -> None:
        """懒加载引擎与会话工厂（asyncio.Lock 保护并发）"""
        async with self._lock:
            await self._do_create_engine()

    async def connect(self) -> None:
        """显式初始化连接池并校验数据库可连接（SELECT 1），失败即抛异常"""
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError

        async with self._lock:
            old_engine = self.engine
            if old_engine is not None:
                self.engine = None
                self.session_factory = None
            await self._do_create_engine()
            if old_engine is not None:
                await old_engine.dispose()

            try:
                async with self.engine.connect() as conn:  # type: ignore[union-attr]
                    await conn.execute(text("SELECT 1"))
            except SQLAlchemyError as e:
                logger.error("mysql_connection_check_failed error=%s url=%s", str(e), repr(self))
                raise
            logger.info("mysql_pool_initialized url=%s", repr(self))

    async def _do_create_engine(self) -> None:
        """创建异步引擎与会话工厂（须在锁内调用）"""
        if self.engine is not None:
            return
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        # create_async_engine 延迟导入：优先取模块属性（兼容测试 monkeypatch 覆盖引擎工厂），
        # 未覆盖时再从 SQLAlchemy 延迟导入（最小安装无需 SQLAlchemy 即可 import 本模块）
        create_async_engine = globals().get("create_async_engine")
        if create_async_engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine

        # S14-3 池名与空闲回收：SQLAlchemy QueuePool 无独立池名参数，池名（=datasource_name）以
        # 日志/指标标签形式落地（慢 SQL/池指标/泄漏均带该标签）；pool_recycle 即 idle 空闲回收机制，
        # 连接空闲超过 pool_recycle 秒后归还时强制重建，防止 MySQL wait_timeout 断连
        engine = create_async_engine(
            self.url,
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_recycle=self.pool_recycle,
            pool_timeout=self.pool_timeout,
            echo=self.echo,
            pool_pre_ping=self.pool_pre_ping,
            connect_args=self.connect_args,
        )
        self.engine = engine
        self.session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
        # 已注册的租户条件过滤器延迟挂载（多租户规范 §2：会话工厂就绪后自动生效）
        if self._tenant_filter is not None:
            self._tenant_filter.install(self.session_factory)
        self._register_sql_timing_events(engine)
        self._register_pool_leak_events(engine)

    def _register_sql_timing_events(self, engine: AsyncEngine) -> None:
        """注册 SQL 耗时监听（§18.5.3 慢 SQL 分级告警：P2 告警 / P1 严重告警）"""
        from sqlalchemy import event

        warning_threshold = self.slow_sql_threshold_seconds
        critical_threshold = self.slow_sql_critical_seconds
        datasource = self.datasource_name
        timing: dict[int, float] = {}

        def _before(conn: Any, cursor: Any, statement: Any, parameters: Any, context: Any, executemany: Any) -> None:
            timing[id(conn)] = time.perf_counter()

        def _after(conn: Any, cursor: Any, statement: Any, parameters: Any, context: Any, executemany: Any) -> None:
            start = timing.pop(id(conn), None)
            if start is None:
                return
            elapsed = time.perf_counter() - start
            if elapsed < warning_threshold:
                return
            sql_preview = _sql_preview(statement)
            if elapsed >= critical_threshold:
                # P1 严重告警：日志 + 慢 SQL 计数指标与明细缓存（§18.5.3）
                logger.error(
                    "mysql_slow_query_critical datasource=%s duration=%.3fs sql=%s",
                    datasource, elapsed, sql_preview,
                )
                record_slow_sql(datasource, elapsed, sql_preview, severity="critical", alert_level="P1")
            else:
                # P2 告警：日志 + 慢 SQL 计数指标与明细缓存（§18.5.3）
                logger.warning(
                    "mysql_slow_query datasource=%s duration=%.3fs sql=%s",
                    datasource, elapsed, sql_preview,
                )
                record_slow_sql(datasource, elapsed, sql_preview, severity="warning", alert_level="P2")

        event.listen(engine.sync_engine, "before_cursor_execute", _before)
        event.listen(engine.sync_engine, "after_cursor_execute", _after)

    def _register_pool_leak_events(self, engine: AsyncEngine) -> None:
        """注册连接泄漏检测（§10.6：借出超过阈值未归还判定泄漏，并计入泄漏指标）"""
        from sqlalchemy import event

        pool = engine.sync_engine.pool
        datasource = self.datasource_name
        leak_threshold = self.leak_detection_threshold_seconds
        checkout_times: dict[int, float] = {}

        def _on_checkout(dbapi_connection: Any, connection_record: Any, connection_proxy: Any) -> None:
            checkout_times[id(dbapi_connection)] = time.perf_counter()

        def _on_checkin(dbapi_connection: Any, connection_record: Any) -> None:
            start = checkout_times.pop(id(dbapi_connection), None)
            if start is not None:
                held_seconds = time.perf_counter() - start
                if held_seconds >= leak_threshold:
                    MYSQL_POOL_CONNECTION_LEAK_TOTAL.labels(datasource).inc()
                    logger.warning(
                        "mysql_connection_leak_detected datasource=%s held=%.3fs threshold=%ss",
                        datasource, held_seconds, leak_threshold,
                    )

        event.listen(pool, "checkout", _on_checkout)
        event.listen(pool, "checkin", _on_checkin)

    def update_pool_metrics(self) -> None:
        """刷新 MySQL 连接池运行指标（§18.5.4，引擎未初始化时各项置 0）。

        供 /metrics 抓取前调用（health 端点统一刷新推送式指标）。
        """
        pool = self.engine.sync_engine.pool if self.engine is not None else None
        record_mysql_pool_metrics(pool, self.datasource_name)

    def replica_names(self) -> list[str]:
        """返回已配置从库名列表（replica_0..N，按 replica_urls 顺序）"""
        return [f"replica_{i}" for i in range(len(self.replica_urls))]

    async def _ensure_replica_engine(self, name: str, url: str) -> None:
        """懒加载指定从库引擎与会话工厂（asyncio.Lock 保护并发，与主库同款）"""
        if name in self._replica_engines:
            return
        async with self._lock:
            if name in self._replica_engines:
                return
            await self._do_create_replica_engine(name, url)

    async def _do_create_replica_engine(self, name: str, url: str) -> None:
        """创建从库异步引擎与会话工厂（须在锁内调用；复用主库池参数与 _build_url 连接参数）"""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        # create_async_engine 延迟导入：优先取模块属性（兼容测试 monkeypatch 覆盖引擎工厂），
        # 未覆盖时再从 SQLAlchemy 延迟导入（最小安装无需 SQLAlchemy 即可 import 本模块）
        create_async_engine = globals().get("create_async_engine")
        if create_async_engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine

        replica_url, connect_args = self._build_url(url, self.replica_username, self.replica_password)
        # 复用主库三层超时（规范 §14.1）：连接建立 / socket 读写
        connect_args["connect_timeout"] = self.connect_args.get("connect_timeout", 10)
        connect_args.setdefault("read_timeout", self.connect_args.get("read_timeout", 30))
        connect_args.setdefault("write_timeout", self.connect_args.get("write_timeout", 30))
        engine = create_async_engine(
            replica_url,
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_recycle=self.pool_recycle,
            pool_timeout=self.pool_timeout,
            echo=self.echo,
            pool_pre_ping=self.pool_pre_ping,
            connect_args=connect_args,
        )
        self._replica_engines[name] = engine
        self._replica_session_factories[name] = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
        # 与主库一致：注册慢 SQL 分级告警与连接泄漏检测（§18.5.3 / §10.6）
        self._register_sql_timing_events(engine)
        self._register_pool_leak_events(engine)
        logger.info("mysql_replica_engine_initialized name=%s url=%s", name, repr(self))

    async def get_replica_session(self, name: str | None = None) -> AsyncSession:
        """获取从库会话（读写分离 S10-2）。

        name 为空时由读写分离路由轮询选择从库；未配置从库 / 指定从库不存在时回退主库（记 warning）。
        """
        if name is None:
            name = self._replica_router.next_replica()
        if name is None:
            logger.warning("mysql_replica_not_available_fallback_to_primary")
            return await self.new_session()
        try:
            index = int(name.rsplit("_", 1)[-1])
        except ValueError:
            index = -1
        if index < 0 or index >= len(self.replica_urls):
            logger.warning("mysql_replica_not_configured_fallback_to_primary name=%s", name)
            return await self.new_session()
        await self._ensure_replica_engine(name, self.replica_urls[index])
        return self._replica_session_factories[name]()

    async def new_session(self) -> AsyncSession:
        """创建并返回一个新的 AsyncSession（调用方负责 close）"""
        await self._ensure_engine()
        return self.session_factory()  # type: ignore[misc]

    async def get_session(self) -> AsyncIterator[AsyncSession]:
        """获取数据库会话（用于 FastAPI Depends 依赖注入）"""
        await self._ensure_engine()
        async with self.session_factory() as session:  # type: ignore[misc]
            yield session

    def get_session_context(self) -> _AsyncSessionContextManager:
        """获取会话上下文管理器（用于 service 层 async with，进入时懒加载引擎）"""
        return _AsyncSessionContextManager(self)

    async def close(self) -> None:
        """关闭连接池，释放所有连接（含全部从库引擎）"""
        engine: AsyncEngine | None = None
        async with self._lock:
            if self.engine is not None:
                engine = self.engine
                self.engine = None
                self.session_factory = None
            replica_engines = list(self._replica_engines.values())
            self._replica_engines.clear()
            self._replica_session_factories.clear()
        if engine is not None:
            await engine.dispose()
            logger.info("mysql_pool_closed")
        for replica_engine in replica_engines:
            await replica_engine.dispose()
        if replica_engines:
            logger.info("mysql_replica_pool_closed count=%d", len(replica_engines))

    async def health_check(self) -> bool:
        """检查数据库连接是否可用"""
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError

        await self._ensure_engine()
        try:
            async with self.engine.connect() as conn:  # type: ignore[union-attr]
                await conn.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError as e:
            logger.error("mysql_health_check_failed error=%s", str(e))
            return False

    async def __aenter__(self) -> "MySQLConfig":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    def __repr__(self) -> str:
        return f"<MySQLConfig url={self.url.split('@')[-1] if '@' in self.url else self.url}>"
