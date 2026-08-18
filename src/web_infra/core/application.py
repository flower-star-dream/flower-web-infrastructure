"""
应用启动器

@Author: 花海
@Date: 2026/08/14 21:00
@Description: 应用启动器（参考 Spring Boot 自动装配），后续所有使用本依赖的项目均通过 Application 启动。
              根据配置自动装配日志、中间件、全局异常处理与各中间件组件（缓存/数据库/MongoDB/对象存储/消息队列/注册发现）。
              默认配置统一收敛于 config/application.default.yml（YAML），业务可通过 application.yml 或环境变量覆盖；
              application 仅做组件装配，不内嵌任何默认配置值；中间件由配置声明式引入（app.web.middlewares），
              多租户/AI 等特殊场景默认不启用，需业务配置显式开启。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Callable

from fastapi import FastAPI

from web_infra.infra.config import ConfigError, CompositeConfigSource, DictConfigSource, Settings
from web_infra.core.capability import CapabilityRegistry
from web_infra.core.extension import ExtensionRegistry
from web_infra.infra.context import RequestContext
from web_infra.infra.error import register_global_exception_handlers
from web_infra.infra.logging import configure_logging
from web_infra.infra.web import TraceIdMiddleware, register_health_endpoints
from web_infra.infra.web.logging_middleware import setup_uvicorn_access_log
from web_infra.infra.web.auth_middleware import AuthMiddleware
from web_infra.infra.web.idempotency_middleware import IdempotencyMiddleware
from web_infra.infra.web.in_memory_idempotency_store import InMemoryIdempotencyStore
from web_infra.infra.web.redis_idempotency_store import RedisIdempotencyStore
from web_infra.infra.web.rate_limit_middleware import RateLimitMiddleware
from web_infra.infra.web.security_headers_middleware import SecurityHeadersMiddleware
from web_infra.capabilities.cache.cache_backend_registry import CacheBackendRegistry
from web_infra.capabilities.db import (
    SqliteSessionFactory,
    TenantQueryFilter,
)
from web_infra.capabilities.db.database_registry import DatabaseRegistry
from web_infra.capabilities.db.database_manager import DatabaseManager
from web_infra.capabilities.db.database_router import TenantDatabaseRouter
from web_infra.capabilities.db.mongo_database_registry import MongoDatabaseRegistry
from web_infra.capabilities.ai.model_gateway import ModelRouter, RouteEntry, ModelGateway
from web_infra.capabilities.ai.model_auto_registrar import ModelAutoRegistrar
from web_infra.capabilities.ai.model_config_store_registry import ModelConfigStoreRegistry
from web_infra.capabilities.ai.sqlalchemy_model_config_store import SqlAlchemyModelConfigStore
from web_infra.capabilities.ai.connection_pool import ConnectionPoolConfig, ConnectionPoolManager
from web_infra.capabilities.ai.quota import QuotaConfig, QuotaManager
from web_infra.capabilities.mq.message_queue_registry import MessageQueueRegistry
from web_infra.capabilities.storage.object_storage_registry import ObjectStorageRegistry
from web_infra.capabilities.registry.service_discovery_registry import ServiceDiscoveryRegistry
from web_infra.capabilities.capacity.assessor import CapacityAssessor
from web_infra.capabilities.capacity.capacity_config import CapacityConfig, DiagnosticAccessConfig, RemoteProbeConfig
from web_infra.capabilities.capacity.capacity_endpoint import register_capacity_endpoints
from web_infra.infra.web.diagnostic_access import DiagnosticAccessGuard

logger = logging.getLogger(__name__)

# 框架提供的中间件注册表（name -> (中间件类, 构造参数构建器)）：
# 业务在 app.web.middlewares 中声明是否引入及参数，如何引入由配置决定。
# 构建器签名 (options, ctx)：ctx 携带装配上下文（settings/components），
# 供依赖框架组件的中间件复用已装配组件（如幂等存储复用 cache 组件 Redis 客户端）。
_MIDDLEWARE_REGISTRY: dict[str, tuple[type, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]]] = {
    "trace_id": (TraceIdMiddleware, lambda options, ctx: {}),
    "auth": (AuthMiddleware, lambda options, ctx: {"whitelist": tuple(options.get("whitelist") or ())}),
    "rate_limit": (
        RateLimitMiddleware,
        lambda options, ctx: {
            "qps": options.get("qps"),
            "burst": options.get("burst"),
            "key_by": options.get("key_by") or "path",
        },
    ),
    "idempotency": (
        IdempotencyMiddleware,
        lambda options, ctx: {
            "store": _build_idempotency_store(options, ctx),
            "ttl_seconds": options.get("ttl_seconds"),
        },
    ),
    # 安全响应头中间件（整改 S25-1）：默认关闭（yml enabled: false，向后兼容），推荐业务显式启用；
    # 头默认值收敛于 yml app.web.middlewares.security_headers，未配置时回落类内安全默认
    "security_headers": (
        SecurityHeadersMiddleware,
        lambda options, ctx: {
            "content_security_policy": options.get("content_security_policy"),
            "x_content_type_options": options.get("x_content_type_options"),
            "x_frame_options": options.get("x_frame_options"),
            "referrer_policy": options.get("referrer_policy"),
        },
    ),
}


def _build_idempotency_store(options: dict[str, Any], ctx: dict[str, Any]) -> Any:
    """按配置构建 API 幂等键存储（app.web.middlewares.idempotency.store_type，规范 §12.6）：
    memory（默认，单实例）/ redis（跨实例原子，复用已装配 cache 组件的 Redis 客户端）。

    :raises ConfigError: store_type=redis 但 cache 组件非 Redis 时快速失败（拿不到 Redis 客户端）
    """
    if (options.get("store_type") or "memory") == "redis":
        cache = (ctx.get("components") or {}).get("cache")
        config = getattr(cache, "config", None)
        if config is None or not hasattr(config, "client"):
            raise ConfigError(
                "app.web.middlewares.idempotency.store_type=redis 需要已启用的 Redis 缓存组件"
                "（app.cache.type=redis），当前拿不到 Redis 客户端",
                key="app.web.middlewares.idempotency",
            )
        return RedisIdempotencyStore(redis=config.client())
    return InMemoryIdempotencyStore()


def _resolve_registry(registry: Any, name: str, key: str) -> Any:
    """按名查组件注册表工厂；未注册抛 ConfigError（避免拼写错误/未注册类型静默回落默认实现）。

    :param registry: 类级注册表（提供 get/registered_names）
    :param name: type 值（yml 配置，如 app.cache.type）
    :param key: 配置键（错误提示定位）
    """
    try:
        return registry.get(name)
    except KeyError:
        raise ConfigError(
            f"{key}={name} 未注册组件实现（内置：{', '.join(registry.registered_names())}；"
            "自定义实现经对应注册表 register 注册后装配）",
            key=key,
        )


class Application:
    """应用启动器：配置驱动的组件自动装配（Spring Boot 风格）"""

    def __init__(
        self,
        settings: Settings | dict[str, Any] | None = None,
        title: str | None = None,
        version: str | None = None,
    ) -> None:
        self.settings = self._resolve_settings(settings)
        self._components: dict[str, Any] = {}
        # 扩展点装配结果（app.extensions.enabled，见 _setup_extensions）：拓扑序启用链与实例表，
        # 生命周期钩子（startup/shutdown）由 _lifespan 在应用启动/停机时按序编排
        self._extension_chain: list[str] = []
        self._extension_instances: dict[str, Any] = {}
        # 容量评估与诊断端点访问控制（app.capacity.enabled 时装配，见 _setup_capacity）：
        # 守卫在 _setup_capacity 构造、供 /capacity 与 /metrics（_setup_health）共用
        self._capacity_assessor: CapacityAssessor | None = None
        self._diagnostic_guard: DiagnosticAccessGuard | None = None

        app_title = title or self.settings.get("app.name")
        app_version = version or self.settings.get("app.version")
        self.app = FastAPI(title=app_title, version=app_version, lifespan=self._lifespan)

    @staticmethod
    def _resolve_settings(settings: Settings | dict[str, Any] | None) -> Settings:
        """归一化配置入参：Settings 实例直接使用；None 用全局实例；
        dict 叠加默认源（环境变量 > 项目 application.yml > 框架默认 yml），保证默认值回落。"""
        if settings is None:
            return Settings.instance()
        if isinstance(settings, Settings):
            return settings
        return Settings(CompositeConfigSource(DictConfigSource(settings), Settings.default_source()))

    def build(self) -> FastAPI:
        """装配应用：日志 -> 能力装配校验 -> 组件装配 -> Web 基础能力 -> 中间件 -> 多租户 -> 健康检查/指标端点。

        组件先于中间件装配：依赖框架组件的中间件（如幂等存储复用 cache 组件 Redis 客户端）装配期可取已装配组件。
        扩展点在组件之后、中间件之前装配：插件 build 可复用已装配组件（ctx.components），
        插件注入的实例同样可被中间件装配复用。
        """
        self._setup_logging()
        self._setup_capabilities()
        self._setup_components()
        self._setup_extensions()
        self._setup_web()
        self._setup_tenant()
        self._setup_capacity()
        self._setup_health()
        return self.app

    def run(self, host: str = "0.0.0.0", port: int = 8000, **kwargs: Any) -> None:
        """启动应用（uvicorn）"""
        import uvicorn

        uvicorn.run(self.app, host=host, port=port, **kwargs)

    def component(self, name: str) -> Any:
        """按名称获取已装配组件（cache/db/mongo/storage/mq/registry）"""
        return self._components.get(name)

    # ------------------------------------------------------------------
    # 内部：从配置读取（不散落默认值，默认值统一在配置文件）
    # ------------------------------------------------------------------

    def _model(self, model_cls: type, prefix: str) -> Any:
        """从配置读取 prefix 段字段，构造 pydantic 配置模型（缺失字段用模型默认值）"""
        kwargs = {
            field_name: value
            for field_name in model_cls.model_fields
            if (value := self.settings.get(f"{prefix}.{field_name}")) is not None
        }
        return model_cls(**kwargs)

    def _build(self, cls: type, prefix: str, fields: list[str]) -> Any:
        """从配置读取 prefix 段字段，构造普通类（缺失字段用构造默认值）"""
        kwargs = {name: value for name in fields if (value := self.settings.get(f"{prefix}.{name}")) is not None}
        return cls(**kwargs)

    # ------------------------------------------------------------------
    # 内部：装配步骤
    # ------------------------------------------------------------------

    def _setup_logging(self) -> None:
        """统一日志格式与输出通道（文本/JSON、控制台/文件可配置，规范 §17；默认值收敛于 yml）。

        输出通道（app.logging.output）：both（默认，控制台+文件同时输出）/ console / file；
        文件路径 app.logging.file、保留天数 app.logging.retention_days；
        自定义通道经 app.logging.sinks 声明（LogSinkInterface SPI，LogSinkRegistry 按名解析）。
        通道配置非法（未注册通道/output=file 缺路径）抛 ConfigError 快速失败。
        """
        fmt = self.settings.get("app.logging.format")
        level_name = self.settings.get("app.logging.level")
        level = getattr(logging, str(level_name).upper(), logging.INFO)
        try:
            configure_logging(
                level=level,
                fmt=fmt,
                output=self.settings.get("app.logging.output") or "both",
                log_file=self.settings.get("app.logging.file"),
                log_retention_days=int(self.settings.get("app.logging.retention_days") or 30),
                sinks=self.settings.get("app.logging.sinks") or {},
            )
        except ValueError as exc:
            raise ConfigError(f"日志配置错误: {exc}", key="app.logging") from exc

    def _setup_capabilities(self) -> None:
        """能力装配校验与启用（app.capabilities.enabled，可选能力依赖包含规则）。

        启用集合按包含关系校验（缺前置自动补足；未知能力/依赖循环抛 ConfigError），
        校验通过后按拓扑序启用各能力（自动导入前置能力与目标能力的框架模块，幂等）。
        未配置 enabled 时跳过（默认不启用任何可选能力，见 yml）。
        """
        enabled = self.settings.get("app.capabilities.enabled") or []
        if not enabled:
            return
        validation = CapabilityRegistry.validate(enabled)
        if not validation.ok:
            details: list[str] = []
            if validation.unknown:
                details.append(f"未注册的能力: {', '.join(sorted(validation.unknown))}")
            if validation.circular:
                details.append("能力依赖循环: " + "; ".join(" -> ".join(c) for c in validation.circular))
            raise ConfigError("能力装配校验失败：" + "；".join(details), key="app.capabilities.enabled")
        for name in enabled:
            CapabilityRegistry.enable(name)

    def _setup_web(self) -> None:
        """装配 Web 基础能力：全局异常处理 + 配置声明的中间件（app.web.middlewares）"""
        register_global_exception_handlers(self.app)
        middlewares = self.settings.get("app.web.middlewares") or {}
        for name, params in middlewares.items():
            if params is False or (isinstance(params, dict) and params.get("enabled") is False):
                continue  # 显式关闭的中间件不引入
            entry = _MIDDLEWARE_REGISTRY.get(name)
            if entry is None:
                raise ConfigError(f"未注册的 Web 中间件: {name}", key=f"app.web.middlewares.{name}")
            middleware_class, build_options = entry
            options = params if isinstance(params, dict) else {}
            ctx = {"settings": self.settings, "components": self._components}
            self.app.add_middleware(middleware_class, **build_options(options, ctx))

    def _setup_components(self) -> None:
        """按配置装配中间件组件，并注入 app.state 供业务代码访问"""
        self._components["cache"] = self._build_cache()
        self._components["db"] = self._build_db()
        self._components["storage"] = self._build_storage()
        self._components["mq"] = self._build_mq()
        self._components["registry"] = self._build_registry()
        self._components["ai"] = self._build_ai()
        if self.settings.get_bool("app.mongo.enabled"):
            self._components["mongo"] = self._build_mongo()

        self.app.state.components = self._components
        for name, component in self._components.items():
            setattr(self.app.state, name, component)
        # 配置挂载到 app.state.settings（业务/组件装配期读取统一配置，如 app.mq.outbox）
        self.app.state.settings = self.settings

    def _setup_extensions(self) -> None:
        """扩展点装配（app.extensions.enabled，统一扩展注册器 ExtensionRegistry）。

        声明即启用：按依赖拓扑序构建各扩展点实例（build(配置段, 装配上下文)），
        实例挂 app.state.extensions 供业务访问；生命周期钩子（startup/shutdown）
        由 _lifespan 在应用启动/停机时按序编排（启动拓扑序、停机逆序）。
        未注册的扩展点/依赖循环装配期快速失败（ConfigError，避免拼写错误/缺前置静默）。
        """
        enabled = self.settings.get("app.extensions.enabled") or []
        if not enabled:
            return
        validation = ExtensionRegistry.validate(enabled)
        if not validation.ok:
            details: list[str] = []
            if validation.unknown:
                details.append(f"未注册的扩展点: {', '.join(sorted(validation.unknown))}")
            if validation.circular:
                details.append("扩展点依赖循环: " + "; ".join(" -> ".join(c) for c in validation.circular))
            raise ConfigError("扩展点装配校验失败：" + "；".join(details), key="app.extensions.enabled")
        instances: dict[str, Any] = {}
        for name in validation.chain:
            entry = ExtensionRegistry.get(name)
            if entry is None or entry.build is None:
                instances[name] = None
                continue
            options = self.settings.get(f"app.extensions.{name}") or {}
            ctx = {"settings": self.settings, "components": self._components}
            instances[name] = entry.build(options, ctx)
        self._extension_chain = list(validation.chain)
        self._extension_instances = instances
        self.app.state.extensions = instances

    def _setup_tenant(self) -> None:
        """多租户装配（app.tenant.enabled=true）：将租户条件过滤器挂载到数据库会话（多租户规范 §2）。

        SQL 自动注入租户条件、strict 模式无上下文拒绝执行；未启用多租户时不装配（默认关闭收敛于 yml）。
        按能力判断（install_tenant_filter）而非具体类型装配，兼容 MySQL/PostgreSQL 等
        任何提供租户过滤能力的数据库实现（DatabaseFactoryInterface 扩展能力）。
        """
        if not self.settings.get_bool("app.tenant.enabled"):
            return
        strict = self.settings.get_bool("app.tenant.strict")
        tenant_filter = TenantQueryFilter(strict=strict)
        db = self._components.get("db")
        if isinstance(db, DatabaseManager):
            for name in db.names:
                install = getattr(db.get(name), "install_tenant_filter", None)
                if callable(install):
                    install(tenant_filter)
            return
        install = getattr(db, "install_tenant_filter", None)
        if callable(install):
            install(tenant_filter)

    def _setup_health(self) -> None:
        """装配健康检查三端点（/health/live 存活、/health/ready 就绪、/health 兼容，整改 S19-1）与指标端点（/metrics），规范 §19.4 / §18.1"""
        register_health_endpoints(
            self.app,
            components=self._components,
            service_name=self.settings.get("app.name"),
            access_guard=self._diagnostic_guard,
        )

    def _setup_capacity(self) -> None:
        """容量评估装配（app.capacity.enabled=true 时，设计文档 §8）：

        - 读取 app.capacity 配置段构造 CapacityAssessor（组合 StaticEstimator + RuntimeSampler
          + RemoteProbe），挂 app.state.capacity 供业务访问；
        - 注册 /capacity 端点（content-negotiation JSON/HTML），生产环境注入
          DiagnosticAccessGuard（IP 白名单，app.diagnostics.access 段；与 /metrics 共用）；
        - 构造守卫并存入 self._diagnostic_guard，供 _setup_health 的 /metrics 复用
          （诊断端点生产访问控制统一，设计文档 §9）。
        未启用时零配置零开销：不构造评估器、不注册端点、不创建采样任务。
        """
        if not self.settings.get_bool("app.capacity.enabled"):
            return
        capacity_config = self._build(
            CapacityConfig,
            "app.capacity",
            [
                "cpu_cores", "memory_mb", "workload_type", "io_concurrency_factor",
                "assumed_avg_latency_ms", "safe_ratio", "slo_alert_ratio",
                "slo_target_availability", "sample_window", "sample_interval",
            ],
        )
        remote_config = RemoteProbeConfig(
            connect_timeout=self.settings.get_float("app.capacity.remote.connect_timeout", 3.0) or 3.0,
            read_timeout=self.settings.get_float("app.capacity.remote.read_timeout", 5.0) or 5.0,
            write_timeout=self.settings.get_float("app.capacity.remote.write_timeout", 5.0) or 5.0,
            pool_timeout=self.settings.get_float("app.capacity.remote.pool_timeout", 5.0) or 5.0,
            timeout=self.settings.get_float("app.capacity.remote.timeout", 10.0) or 10.0,
            max_retries=int(self.settings.get("app.capacity.remote.max_retries", 0) or 0),
            diff_interval=self.settings.get_float("app.capacity.remote.diff_interval", 0.0) or 0.0,
            max_response_bytes=int(self.settings.get("app.capacity.remote.max_response_bytes", 10 * 1024 * 1024) or 0),
        )
        targets = self.settings.get("app.capacity.remote_targets") or ()
        from dataclasses import replace

        capacity_config = replace(capacity_config, remote=remote_config, remote_targets=tuple(targets))

        # 诊断端点访问守卫（生产 IP 白名单）先于端点注册构造：
        # /capacity 与 /metrics（_setup_health 晚于本方法）共用同一守卫（设计文档 §9）
        diag_config = DiagnosticAccessConfig(
            enabled=self.settings.get_bool("app.diagnostics.access.enabled", True),
            allowed_cidrs=tuple(self.settings.get("app.diagnostics.access.allowed_cidrs") or ()),
        )
        self._diagnostic_guard = DiagnosticAccessGuard(
            enabled=diag_config.enabled,
            allowed_cidrs=diag_config.allowed_cidrs,
        )

        self._capacity_assessor = CapacityAssessor(self.settings, capacity_config)
        register_capacity_endpoints(
            self.app,
            self._capacity_assessor,
            service_name=self.settings.get("app.name"),
            access_guard=self._diagnostic_guard,
        )
        self.app.state.capacity = self._capacity_assessor

    async def _start_capacity_sampler(self) -> None:
        """启动容量采样任务（startup 钩子）：评估器装配后才可启动，未启用时跳过。"""
        if self._capacity_assessor is not None:
            await self._capacity_assessor.start()

    async def _stop_capacity_sampler(self) -> None:
        """停止容量采样任务（shutdown 钩子）：幂等，未启用时跳过。"""
        if self._capacity_assessor is not None:
            await self._capacity_assessor.stop()

    # ------------------------------------------------------------------
    # 内部：组件构建（按 type 选择实现）
    # ------------------------------------------------------------------

    def _build_cache(self) -> Any:
        """缓存组件：按 app.cache.type 经 CacheBackendRegistry 按名装配（内置 memory/redis，自定义经注册表接入）"""
        cache_type = self.settings.get("app.cache.type") or "memory"
        return _resolve_registry(CacheBackendRegistry, cache_type, "app.cache.type")(self.settings)

    def _build_db(self) -> Any:
        """数据库组件（DatabaseFactoryInterface SPI，DatabaseRegistry 按名装配）：
        - 单源：按 app.db.type 经注册表按名装配（内置 mysql/sqlite，自定义如 PostgreSQL 经 register 接入）；
        - 混合多数据源（app.db.instances，每实例带 type 字段）：装配为 DatabaseManager 按名/租户路由，
          支持 MySQL/PostgreSQL 等不同数据库并存；
        - 多租户独立库（app.db.mysql.instances，向后兼容旧格式）：全 MySQL 多源同样走 DatabaseManager。
        未注册的 db.type 启动期快速失败（ConfigError，避免拼写错误/未注册类型静默回落 sqlite）。"""
        instances = self.settings.get("app.db.instances")
        if isinstance(instances, dict) and instances:
            return self._build_multi_datasource(instances)
        legacy_instances = self.settings.get("app.db.mysql.instances")
        if isinstance(legacy_instances, dict) and legacy_instances:
            return self._build_multi_datasource(legacy_instances)
        db_type = self.settings.get("app.db.type") or "mysql"
        params = self._db_params(db_type)
        return _resolve_registry(DatabaseRegistry, db_type, "app.db.type")(params)

    def _db_params(self, db_type: str) -> dict[str, Any]:
        """读取 app.db.<type> 段作为单源实例连接参数（非 None 字段；instances 多源由 _build_db 分支处理）"""
        data = self.settings.get(f"app.db.{db_type}") or {}
        return {k: v for k, v in data.items() if v is not None and k != "instances"}

    def _build_multi_datasource(self, instances: dict[str, dict[str, Any]]) -> DatabaseManager:
        """按多数据源配置装配 DatabaseManager（共享连接池 + 租户动态路由）：
        - app.db.instances（通用混合多源）：每实例带 type 字段（缺省 mysql），按 DatabaseRegistry 按名构建，
          支持 MySQL/PostgreSQL 等不同数据库并存；
        - app.db.mysql.instances（多租户独立库模式，向后兼容）：实例无 type 字段时缺省回落 mysql。
        """
        connections: dict[str, Any] = {}
        for name, params in instances.items():
            db_type = params.get("type") or "mysql"
            instance_params = {k: v for k, v in params.items() if k not in ("type", "instances") and v is not None}
            factory = _resolve_registry(DatabaseRegistry, db_type, f"app.db.instances.{name}")
            connections[name] = factory({**instance_params, "datasource_name": name})
        mapping = self.settings.get("app.db.router.mapping")
        pattern = self.settings.get("app.db.router.pattern")
        router = TenantDatabaseRouter(mapping=mapping or {}, pattern=pattern or "tenant_{tenant_id}")
        return DatabaseManager(connections, router)

    def _build_mongo(self) -> Any:
        """MongoDB 组件（MongoDatabaseFactoryInterface SPI，MongoDatabaseRegistry 按名装配）：
        - 仅当 app.mongo.enabled=true 时装配（默认关闭收敛于 yml）；
        - 按 app.mongo.type 经注册表按名装配（内置 beanie 默认实现，自定义文档数据库经 register 接入）；
        - 未注册的 mongo.type 启动期快速失败（ConfigError，避免拼写错误/未注册类型静默回落）。
        """
        mongo_type = self.settings.get("app.mongo.type") or "beanie"
        params = self._mongo_params()
        return _resolve_registry(MongoDatabaseRegistry, mongo_type, "app.mongo.type")(params)

    def _mongo_params(self) -> dict[str, Any]:
        """读取 app.mongo 段作为实例连接参数（排除 enabled/type 装配字段）"""
        data = self.settings.get("app.mongo") or {}
        return {k: v for k, v in data.items() if v is not None and k not in ("enabled", "type")}

    def _build_storage(self) -> Any:
        """对象存储组件：按 app.storage.type 经 ObjectStorageRegistry 按名装配（内置 local/minio，自定义经注册表接入）"""
        storage_type = self.settings.get("app.storage.type") or "local"
        return _resolve_registry(ObjectStorageRegistry, storage_type, "app.storage.type")(self.settings)

    def _build_mq(self) -> Any:
        """消息队列组件：按 app.mq.type 经 MessageQueueRegistry 按名装配（内置 memory/rocketmq，自定义经注册表接入）"""
        mq_type = self.settings.get("app.mq.type") or "memory"
        return _resolve_registry(MessageQueueRegistry, mq_type, "app.mq.type")(self.settings)

    def _build_registry(self) -> Any:
        """服务注册发现组件：按 app.registry.type 经 ServiceDiscoveryRegistry 按名装配（内置 memory/nacos，自定义经注册表接入）"""
        registry_type = self.settings.get("app.registry.type") or "memory"
        return _resolve_registry(ServiceDiscoveryRegistry, registry_type, "app.registry.type")(self.settings)

    def _build_ai(self) -> Any:
        """AI 组件：app.ai.enabled=true 时装配统一模型网关（AI 规范 §2.2/§17.4）。

        模型配置来源（app.ai.store.type，ModelConfigStoreInterface SPI）：
        - yml（默认）：app.ai.models 配置清单 -> 供应商 SPI 注册表（业务代码/配置文件写死供应商）；
        - db：ai_model_config 表（SqlAlchemyModelConfigStore），数据源跟随 app.db.type
          （mysql 复用数据库组件 AsyncSession 会话工厂；sqlite 走独立 SQLAlchemy aiosqlite 引擎），
          启动生命周期内经 register_from_store 自动注册；
        - 自定义来源（配置中心/Redis 等）：经 ModelConfigStoreRegistry.register 注册工厂后按 type 装配，
          未注册的 store.type 启动期快速失败（ConfigError，避免配置拼写错误静默回落）。
        默认 OpenAI 兼容协议（/v1/chat/completions），自定义供应商经 ModelProviderFactory 注册后
        按 provider 字段自动装配。路由由 app.ai.model_gateway.routes 按模型逻辑名声明场景主备。
        默认不启用（yml app.ai.enabled=false），需业务配置显式开启。"""
        if not self.settings.get_bool("app.ai.enabled"):
            return None
        # 1) 自动注册：配置清单/数据库 -> 供应商注册表（同 model_code 覆盖注册）
        registrar = ModelAutoRegistrar()
        store_type = self.settings.get("app.ai.store.type") or "yml"
        if store_type == "db":
            # 数据库模型配置来源：store 挂到组件，启动生命周期内经 register_from_store 自动注册（异步 I/O）
            self._components["ai_model_config_store"] = self._build_ai_model_store()
        else:
            try:
                factory = ModelConfigStoreRegistry.get(store_type)
            except KeyError:
                raise ConfigError(
                    f"app.ai.store.type={store_type} 未注册模型配置来源"
                    "（内置：yml/db；自定义来源经 ModelConfigStoreRegistry.register 注册后装配）",
                    key="app.ai.store.type",
                )
            if store_type == "yml":
                models = self.settings.get("app.ai.models") or []
                if models:
                    registrar.register_configs(ModelAutoRegistrar.from_dicts(list(models)))
            else:
                # 自定义来源（SPI 接入点）：实例挂组件，启动生命周期内经 register_from_store 自动注册
                self._components["ai_model_config_store"] = factory()
        self._components["ai_registrar"] = registrar
        # 2) 场景路由（按模型逻辑名声明主备降级）
        routes = self.settings.get("app.ai.model_gateway.routes") or {}
        route_entries = {
            scene: RouteEntry(
                primary=str(item.get("primary", "")),
                backups=tuple(str(b) for b in (item.get("backups") or [])),
            )
            for scene, item in routes.items()
            if item.get("primary")
        }
        router = ModelRouter(
            route_entries,
            default_scene=self.settings.get("app.ai.model_gateway.default_scene"),
        )
        pool_manager = ConnectionPoolManager(
            self._build(
                ConnectionPoolConfig,
                "app.ai.connection_pool",
                [
                    "stream_max_connections", "stream_max_keepalive_connections",
                    "sync_max_connections", "sync_max_keepalive_connections",
                    "connect_timeout_seconds", "stream_read_timeout_seconds", "sync_read_timeout_seconds",
                ],
            )
        )
        quota = self._build(QuotaConfig, "app.ai.quota", ["max_calls", "max_tokens", "max_cost", "window_seconds"])
        quota_manager = (
            QuotaManager(default_config=quota)
            if (quota.max_calls or quota.max_tokens or quota.max_cost)
            else None
        )
        return ModelGateway(router, pool_manager=pool_manager, quota_manager=quota_manager)

    def _build_ai_model_store(self) -> Any:
        """构建数据库模型配置来源（app.ai.store.type=db）：数据源跟随用户配置的数据库组件（不锁死 MySQL）。

        支持的数据源（app.db.type）：
        - mysql（默认）：复用 MySQLDatabase 的 SQLAlchemy AsyncSession 会话工厂（模型配置表与业务库同库部署）；
        - 多数据源（DatabaseManager，多租户独立库模式）：取首个已注册数据源的会话工厂；
        - sqlite：基于 SqliteSessionFactory 的数据文件路径构建独立 SQLAlchemy aiosqlite 异步引擎
          （框架 sqlite 组件为同步 sqlite3 会话，模型配置表走独立异步连接；:memory: 场景为独立内存库，
          与业务会话不共享，建议使用文件路径）。
        自定义数据源经 DatabaseFactoryInterface 接入框架后，提供 SQLAlchemy AsyncSession 会话工厂即可复用。

        :raises ConfigError: db 组件缺失或拿不到 SQLAlchemy 异步会话工厂时快速失败
        """
        db = self._components.get("db")
        session_factory = getattr(db, "session_factory", None)
        if session_factory is None and isinstance(db, DatabaseManager):
            names = db.names
            if names:
                session_factory = getattr(db.get(names[0]), "session_factory", None)
        if session_factory is not None:
            return SqlAlchemyModelConfigStore(session_factory)
        if isinstance(db, SqliteSessionFactory):
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            engine = create_async_engine(f"sqlite+aiosqlite:///{db.db_path}")
            return SqlAlchemyModelConfigStore(async_sessionmaker(engine, expire_on_commit=False), engine=engine)
        raise ConfigError(
            "app.ai.store.type=db 需要已装配的数据库组件提供 SQLAlchemy 异步会话工厂"
            "（app.db.type=mysql 或 sqlite；自定义数据源实现 DatabaseFactoryInterface 并提供异步会话工厂）",
            key="app.ai.store.type",
        )

    # ------------------------------------------------------------------
    # 内部：生命周期（优雅停机，规范 §19.6）
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI) -> AsyncGenerator[None, None]:
        """应用生命周期：启动前清理上下文、模型配置来源自动注册、接管 uvicorn 访问日志；停机时释放可关闭组件"""
        RequestContext.clear()
        # 装配了访问日志中间件时，启动阶段关闭 uvicorn 原生访问日志（由中间件输出唯一访问日志，避免重复）。
        # 自定义 lifespan 下 Starlette 不会执行 router 的 on_startup 事件，故在此显式调用
        # （uvicorn Config 日志配置早于 lifespan 启动，此处执行时机在接受连接之前，原生日志全程不输出）。
        setup_uvicorn_access_log(self.app)
        await self._register_ai_models_from_store()
        await self._run_extension_startups()
        await self._start_capacity_sampler()
        yield
        await self._stop_capacity_sampler()
        await self._run_extension_shutdowns()
        await self._shutdown()

    async def _run_extension_startups(self) -> None:
        """扩展点启动钩子：按拓扑序（前置先启动）执行各扩展点 startup(build 产物)（同步/异步皆可）。

        启动失败由钩子自行抛错/记录（与组件装配一致：不吞异常，启动失败即应用启动失败）。
        """
        for name in self._extension_chain:
            entry = ExtensionRegistry.get(name)
            if entry is None or entry.startup is None:
                continue
            result = entry.startup(self._extension_instances.get(name))
            if inspect.isawaitable(result):
                await result

    async def _run_extension_shutdowns(self) -> None:
        """扩展点停机钩子：按逆拓扑序（后启先停）执行各扩展点 shutdown(build 产物)（同步/异步皆可）。

        停机先于框架组件 close 执行：插件可能依赖框架组件（如 Redis 客户端），先用完再关底层。
        """
        for name in reversed(self._extension_chain):
            entry = ExtensionRegistry.get(name)
            if entry is None or entry.shutdown is None:
                continue
            result = entry.shutdown(self._extension_instances.get(name))
            if inspect.isawaitable(result):
                await result

    async def _register_ai_models_from_store(self) -> None:
        """模型配置来源（app.ai.store.type=db 或自定义 SPI 来源）：启动时全量加载并自动同步 SPI 注册表（AI 规范 §17.4）。

        注册失败仅记录 error 日志不阻断启动（来源暂不可用时应用仍可提供非 AI 能力），
        模型调用将回落 E4-AI-001（模型/供应商未配置）明确错误。
        """
        registrar = self._components.get("ai_registrar")
        store = self._components.get("ai_model_config_store")
        if registrar is None or store is None:
            return
        try:
            registered = await registrar.register_from_store(store)
            logger.info("ai_model_config_db_register_count=%d", len(registered))
        except Exception as exc:  # 来源未就绪/表缺失：记录错误，不阻断应用启动
            logger.error("ai_model_config_db_register_failed err=%s", exc)

    async def _shutdown(self) -> None:
        """优雅停机（规范 §19.2 摘流量→等待窗口→连接排空→优雅退出）。

        停机流程：
        1) 摘流量/就绪摘除：由部署层（K8s preStop / 注册中心下线）在触发停机前完成；
           /health/ready 就绪探针随组件关闭自然返回 DOWN（health 模块无独立就绪开关，框架不做额外状态翻转）。
        2) 等待窗口：sleep app.graceful_shutdown_wait_seconds（默认 0，保持旧行为与测试兼容；
           生产环境建议配置 ≥10s），等待窗口内新流量已不再进入，存量请求继续排空。
        3) 连接排空与资源释放：依次关闭各组件 close/stop（数据库连接池、Redis、MQ 等）。
        """
        wait_seconds = float(self.settings.get_float("app.graceful_shutdown_wait_seconds", 0.0) or 0.0)
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        for component in self._components.values():
            method = getattr(component, "close", None) or getattr(component, "stop", None)
            if callable(method):
                result = method()
                if inspect.isawaitable(result):
                    await result


def create_app(settings: Settings | dict[str, Any] | None = None, **kwargs: Any) -> FastAPI:
    """便捷入口：创建并装配应用（推荐项目入口调用）"""
    return Application(settings, **kwargs).build()
