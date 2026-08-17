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
from typing import Any, Callable, cast

from fastapi import FastAPI

from web_infra.config import ConfigError, CompositeConfigSource, DictConfigSource, Settings
from web_infra.context import RequestContext
from web_infra.error import register_global_exception_handlers
from web_infra.logging import configure_logging
from web_infra.web import TraceIdMiddleware, register_health_endpoints
from web_infra.web.auth_middleware import AuthMiddleware
from web_infra.web.idempotency_middleware import IdempotencyMiddleware
from web_infra.web.in_memory_idempotency_store import InMemoryIdempotencyStore
from web_infra.web.rate_limit_middleware import RateLimitMiddleware
from web_infra.web.security_headers_middleware import SecurityHeadersMiddleware
from web_infra.security.jwt_util import JWTUtil
from web_infra.cache import (
    CacheConfig,
    MemoryCacheBackend,
)
from web_infra.db import (
    MongoDBConfig,
    MySQLConfig,
    MySQLConnectionSettings,
    MySQLDatabase,
    RedisCacheBackend,
    RedisConfig,
    SqliteSessionFactory,
    TenantQueryFilter,
)
from web_infra.db.database_manager import DatabaseManager
from web_infra.db.database_router import TenantDatabaseRouter
from web_infra.ai.model_gateway import ModelRouter, RouteEntry, ModelGateway
from web_infra.ai.model_auto_registrar import ModelAutoRegistrar
from web_infra.ai.connection_pool import ConnectionPoolConfig, ConnectionPoolManager
from web_infra.ai.quota import QuotaConfig, QuotaManager
from web_infra.mq import InMemoryMessageQueue, RocketMqConfig, RocketMqPublisher
from web_infra.storage import (
    LocalObjectStorage,
    StorageConfig,
    MinioObjectStorage,
    MinioStorageConfig,
)
from web_infra.registry import (
    InMemoryServiceRegistry,
    NacosDiscoveryClient,
)
from web_infra.config import NacosProperties

# 框架提供的中间件注册表（name -> (中间件类, 构造参数构建器)）：
# 业务在 app.web.middlewares 中声明是否引入及参数，如何引入由配置决定
_MIDDLEWARE_REGISTRY: dict[str, tuple[type, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    "trace_id": (TraceIdMiddleware, lambda options: {}),
    "auth": (AuthMiddleware, lambda options: {"whitelist": tuple(options.get("whitelist") or ())}),
    "rate_limit": (
        RateLimitMiddleware,
        lambda options: {
            "qps": options.get("qps"),
            "burst": options.get("burst"),
            "key_by": options.get("key_by") or "path",
        },
    ),
    "idempotency": (
        IdempotencyMiddleware,
        lambda options: {"store": InMemoryIdempotencyStore(), "ttl_seconds": options.get("ttl_seconds")},
    ),
    # 安全响应头中间件（整改 S25-1）：默认关闭（yml enabled: false，向后兼容），推荐业务显式启用；
    # 头默认值收敛于 yml app.web.middlewares.security_headers，未配置时回落类内安全默认
    "security_headers": (
        SecurityHeadersMiddleware,
        lambda options: {
            "content_security_policy": options.get("content_security_policy"),
            "x_content_type_options": options.get("x_content_type_options"),
            "x_frame_options": options.get("x_frame_options"),
            "referrer_policy": options.get("referrer_policy"),
        },
    ),
}


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
        """装配应用：日志 -> Web 基础能力 -> 中间件组件 -> 多租户 -> 健康检查/指标端点"""
        self._setup_logging()
        self._setup_web()
        self._setup_components()
        self._setup_tenant()
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
        """统一日志格式（文本/JSON 可配置，规范 §17；格式与级别默认值收敛于 yml）"""
        fmt = self.settings.get("app.logging.format")
        level_name = self.settings.get("app.logging.level")
        level = getattr(logging, str(level_name).upper(), logging.INFO)
        configure_logging(level=level, fmt=fmt)

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
            self.app.add_middleware(middleware_class, **build_options(options))

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

    def _setup_tenant(self) -> None:
        """多租户装配（app.tenant.enabled=true）：将租户条件过滤器挂载到数据库会话（多租户规范 §2）。

        SQL 自动注入租户条件、strict 模式无上下文拒绝执行；未启用多租户时不装配（默认关闭收敛于 yml）。
        """
        if not self.settings.get_bool("app.tenant.enabled"):
            return
        strict = self.settings.get_bool("app.tenant.strict")
        tenant_filter = TenantQueryFilter(strict=strict)
        db = self._components.get("db")
        if isinstance(db, MySQLDatabase):
            db.install_tenant_filter(tenant_filter)
        elif isinstance(db, DatabaseManager):
            for name in db.names:
                connection = db.get(name)
                if isinstance(connection, MySQLDatabase):
                    connection.install_tenant_filter(tenant_filter)

    def _setup_health(self) -> None:
        """装配健康检查三端点（/health/live 存活、/health/ready 就绪、/health 兼容，整改 S19-1）与指标端点（/metrics），规范 §19.4 / §18.1"""
        register_health_endpoints(
            self.app,
            components=self._components,
            service_name=self.settings.get("app.name"),
        )

    # ------------------------------------------------------------------
    # 内部：组件构建（按 type 选择实现）
    # ------------------------------------------------------------------

    def _build_cache(self) -> Any:
        """缓存组件：memory（默认）/ redis（默认值与类型收敛于 yml）"""
        cache_type = self.settings.get("app.cache.type")
        if cache_type == "redis":
            config = self._build(
                RedisConfig,
                "app.cache.redis",
                [
                    "host", "port", "db", "password", "username", "max_connections",
                    "decode_responses", "socket_connect_timeout", "socket_timeout",
                    "socket_keepalive", "health_check_interval", "retry_on_timeout",
                ],
            )
            # 启用 Redis 时 JWT Token 状态存储默认走 Redis（复用同一 Redis 实例；
            # 未启用回落内存，业务可经 JWTUtil.configure 注入自定义实现覆盖）
            JWTUtil.set_redis_config(config)
            return RedisCacheBackend(config=config)
        return MemoryCacheBackend(CacheConfig(max_size=cast(int, self.settings.get_int("app.cache.max_size"))))

    def _build_db(self) -> Any:
        """数据库组件：mysql（默认，通用 DatabaseFactoryInterface 接口）/ sqlite（轻量参考）。
        多数据源（app.db.mysql.instances，多租户独立库/Schema 模式）默认关闭（yml 中空字典即单数据源）。"""
        db_type = self.settings.get("app.db.type")
        if db_type == "mysql":
            instances = self.settings.get("app.db.mysql.instances")
            if isinstance(instances, dict) and instances:
                return self._build_multi_datasource(instances)
            settings = self._model(MySQLConnectionSettings, "app.db.mysql")
            return MySQLDatabase(MySQLConfig(settings=settings, datasource_name="default"))
        return SqliteSessionFactory(db_path=self.settings.get("app.db.sqlite.path"))

    def _build_multi_datasource(self, instances: dict[str, dict[str, Any]]) -> DatabaseManager:
        """按多数据源配置装配 DatabaseManager（共享连接池 + 租户动态路由）"""
        connections: dict[str, Any] = {}
        for name, params in instances.items():
            settings = MySQLConnectionSettings(**params)
            connections[name] = MySQLDatabase(MySQLConfig(settings=settings, datasource_name=name))
        mapping = self.settings.get("app.db.router.mapping")
        pattern = self.settings.get("app.db.router.pattern")
        router = TenantDatabaseRouter(mapping=mapping or {}, pattern=pattern or "tenant_{tenant_id}")
        return DatabaseManager(connections, router)

    def _build_mongo(self) -> Any:
        """MongoDB 组件（仅当 app.mongo.enabled=true 时装配，默认关闭收敛于 yml）"""
        return self._build(
            MongoDBConfig,
            "app.mongo",
            [
                "url", "database", "username", "password", "max_pool_size", "min_pool_size",
                "max_idle_time_ms", "connect_timeout_ms", "server_selection_timeout_ms",
                "socket_timeout_ms", "wait_queue_timeout_ms", "heartbeat_frequency_ms", "retry_writes",
            ],
        )

    def _build_storage(self) -> Any:
        """对象存储组件：local（默认）/ minio（默认值收敛于 yml）"""
        storage_type = self.settings.get("app.storage.type")
        if storage_type == "minio":
            config = self._model(MinioStorageConfig, "app.storage.minio")
            return MinioObjectStorage(config)
        return LocalObjectStorage(StorageConfig(base_dir=self.settings.get("app.storage.base_dir")))

    def _build_mq(self) -> Any:
        """消息队列组件：memory（默认）/ rocketmq（默认值收敛于 yml）"""
        mq_type = self.settings.get("app.mq.type")
        if mq_type == "rocketmq":
            config = self._model(RocketMqConfig, "app.mq.rocketmq")
            return RocketMqPublisher(config)
        return InMemoryMessageQueue()

    def _build_registry(self) -> Any:
        """服务注册发现组件：memory（默认）/ nacos（默认值收敛于 yml）"""
        registry_type = self.settings.get("app.registry.type")
        if registry_type == "nacos":
            config = self._model(NacosProperties, "app.registry.nacos")
            return NacosDiscoveryClient(config)
        return InMemoryServiceRegistry(
            instance_expire_seconds=cast(int, self.settings.get_int("app.registry.expire_seconds"))
        )

    def _build_ai(self) -> Any:
        """AI 组件：app.ai.enabled=true 时装配统一模型网关（AI 规范 §2.2/§17.4）。

        模型自动注册：yml app.ai.models 配置清单 -> 供应商 SPI 注册表，业务代码无需手动注册；
        默认 OpenAI 兼容协议（/v1/chat/completions），自定义供应商经 ModelProviderFactory 注册后
        按 provider 字段自动装配。路由由 app.ai.model_gateway.routes 按模型逻辑名声明场景主备。
        默认不启用（yml app.ai.enabled=false），需业务配置显式开启。"""
        if not self.settings.get_bool("app.ai.enabled"):
            return None
        # 1) 自动注册：yml 配置清单 -> 供应商注册表（同 model_code 覆盖注册）
        registrar = ModelAutoRegistrar()
        models = self.settings.get("app.ai.models") or []
        if models:
            registrar.register_configs(ModelAutoRegistrar.from_dicts(list(models)))
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

    # ------------------------------------------------------------------
    # 内部：生命周期（优雅停机，规范 §19.6）
    # ------------------------------------------------------------------

    async def _lifespan(self, app: FastAPI) -> Any:
        """应用生命周期：启动前清理上下文，停机时释放可关闭组件"""
        RequestContext.clear()
        yield
        await self._shutdown()

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
