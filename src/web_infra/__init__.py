"""
Web 系统通用后端基础设施

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 通用基础设施入口，导出统一响应、错误码、异常、请求上下文、日志、韧性、缓存、
              数据库、消息队列、对象存储、服务注册发现、负载均衡、HTTP 客户端、配置、安全、
              监控、工具、AI 与应用启动器等核心能力，供单体与微服务项目作为基础依赖复用。
              依赖解耦（2026-08-15）：db 相关依赖 sqlalchemy/redis/mongo 的名字惰性导出，
              最小安装（未装 sqlalchemy/redis/mongo）`import web_infra` 不触发导入。
"""
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from web_infra.db import (
        Base,
        DatabaseManager,
        MongoDBConfig,
        MySQLConfig,
        MySQLDatabase,
        RedisCacheBackend,
        RedisConfig,
        TenantAwareMixin,
        TenantQueryFilter,
    )

from web_infra.result import Result, PageResult, PageData
from web_infra.error import (
    ErrorCode,
    ErrorCodeRegistry,
    CommonErrorCode,
    parse_category,
    derive_http_status,
    is_client_error,
    is_retryable,
    converge_error_code,
    WebInfraException,
    BizException,
    ParamException,
    PermException,
    AuthException,
    register_global_exception_handlers,
)
from web_infra.context import RequestContext, RequestContextSnapshot, generate_trace_id
from web_infra.logging import configure_logging, get_logger
from web_infra.logging.masking import mask
from web_infra.resilience import (
    RetryConfig,
    retry,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerState,
    CircuitOpenError,
    RateLimitConfig,
    TokenBucketRateLimiter,
    DistributedLock,
)
from web_infra.ai import (
    ModelProviderInterface,
    ModelProviderRegistry,
    ChatRole,
    FinishReason,
    ChatMessage,
    Usage,
    ChatRequest,
    ChatResponse,
    ChatStreamChunk,
    EmbeddingRequest,
    EmbeddingResponse,
    AiErrorCode,
    ModelConfig,
    ModelConfigStoreInterface,
    DictModelConfigStore,
    ModelConfigManager,
    PromptTemplate,
    PromptTemplateStoreInterface,
    InMemoryPromptTemplateStore,
    PromptTemplateFiller,
    ContextWindowErrorParser,
    ContextTruncator,
    ContextWindowRetryPolicy,
    DocumentChunkerInterface,
    MarkdownChunker,
    VectorStoreInterface,
    InMemoryVectorStore,
    EmbeddingProviderInterface,
    RerankerInterface,
    Retriever,
    GuardAction,
    GuardResult,
    ContentGuardInterface,
    RuleBasedContentGuard,
    UsageRecord,
    UsageRecordStoreInterface,
    UsageAccounting,
    AICache,
    PromptAssembler,
    ConnectionPoolConfig,
    ConnectionPoolManager,
    ConcurrencyGuard,
    QuotaConfig,
    QuotaCounter,
    QuotaStoreInterface,
    InMemoryQuotaStore,
    QuotaManager,
    RouteEntry,
    ModelGatewayConfig,
    ModelRouter,
    ModelGateway,
)
from web_infra.web import (
    RequestContextMiddleware,
    TraceIdMiddleware,
    BigIntJSONResponse,
    setup_cors,
    LoggingMiddleware,
    setup_logging_middleware,
    register_health_endpoints,
    format_sse,
    format_sse_error,
    sse_response,
    IdempotencyResult,
    IdempotencyStoreInterface,
    InMemoryIdempotencyStore,
    RedisIdempotencyStore,
    IdempotencyMiddleware,
    AuthMiddleware,
    RateLimitMiddleware,
)
from web_infra.config import (
    ConfigSourceInterface,
    ConfigError,
    EnvConfigSource,
    DictConfigSource,
    JsonFileConfigSource,
    YamlConfigSource,
    CompositeConfigSource,
    Settings,
    BaseConfig,
    ConfigClientInterface,
    NacosConfigClient,
    NacosConfigLoader,
    NacosProperties,
)
from web_infra.constants import (
    AuthConstant,
    CacheKeyBuilder,
    InfraConstant,
    ParamConstant,
    SysConstant,
    BizConstant,
)
from web_infra.cache import KeyBuilder, CacheBackendInterface, CacheConfig, MemoryCacheBackend
from web_infra.cache.tenant_key_builder import TenantKeyBuilder
from web_infra.db import (
    DatabaseConfig,
    PageQuery,
    SqliteSessionFactory,
    DatabaseSessionInterface,
    DatabaseFactoryInterface,
    MySQLConnectionSettings,
    release_session_connection,
    connection_released,
    TenantGuard,
    DatabaseRouterInterface,
    TenantDatabaseRouter,
    SessionScopeMixin,
    provide_db_session,
)
from web_infra.mq import (
    MqConfig,
    RetryableError,
    NonRetryableError,
    Message,
    MessagePublisherInterface,
    MessageConsumerInterface,
    InMemoryMessageQueue,
    RocketMqConfig,
    RocketMqPublisher,
    MessageIdempotencyStoreInterface,
    InMemoryMessageIdempotencyStore,
    RedisMessageIdempotencyStore,
    IdempotentConsumer,
    RetryableConsumer,
    OutboxStatus,
    OutboxRecord,
    OutboxStoreInterface,
    InMemoryOutboxStore,
    MysqlOutboxStore,
    OutboxPublisher,
    OutboxCleaner,
    DlqConsumer,
    requeue_dlq_to_outbox,
    register_outbox_tasks,
)
from web_infra.storage import (
    StorageConfig,
    ObjectStorageInterface,
    LocalObjectStorage,
    MinioStorageConfig,
    MinioObjectStorage,
    UploadStatus,
    UploadTask,
    UploadStoreInterface,
    InMemoryUploadStore,
    PartStorageInterface,
    LocalPartStorage,
    MinioPartStorage,
    MultipartUploadService,
)
from web_infra.payment import (
    PaymentCallback,
    PaymentCallbackDispatcher,
    PaymentCallbackHandler,
    PaymentCallbackVerifier,
    PaymentGateway,
    PaymentGatewayRegistry,
    PaymentPrepayRequest,
    PaymentPrepayResponse,
    PaymentOrder,
    PaymentRefundRequest,
    PaymentRefundResponse,
    PaymentScene,
    PaymentStatus,
    RefundStatus,
    PaymentErrorCode,
    PaymentConfig,
)
from web_infra.schedule import ScheduledTask, TaskScheduler
from web_infra.registry import (
    ServiceInstance,
    ServiceRegistryInterface,
    NacosDiscoveryClient,
    NacosRegistration,
    InMemoryServiceRegistry,
)
from web_infra.loadbalance import LoadBalancerInterface, RandomBalancer, RoundRobinBalancer, WeightedRoundRobinBalancer
from web_infra.http import FeignClient, FeignClientConfig, build_feign_client, default_service_fallback
from web_infra.security import (
    JWTUtil,
    TokenVerifyStatus,
    PasswordEncoder,
    SecureConfigLoader,
    PrivacyGuard,
    PiiResult,
    PiiMatch,
    CaptchaStoreInterface,
    InMemoryCaptchaStore,
    RedisCaptchaStore,
    CaptchaService,
    LoginFailLockService,
    PermissionGuard,
    OAuth2Client,
    OAuth2ClientRegistry,
    InMemoryOAuth2ClientRegistry,
    OAuth2TokenService,
    JwtTokenStore,
    InMemoryJwtTokenStore,
    RedisJwtTokenStore,
    JwtKeyProvider,
    EnvJwtKeyProvider,
    SocialPlatform,
    SocialAccessToken,
    SocialUserInfo,
    SocialBinding,
    SocialBindingStore,
    InMemorySocialBindingStore,
    SocialPlatformRegistry,
    DemoSocialPlatform,
    SocialLoginResult,
    SocialLoginService,
)
from web_infra.task import TaskStatus, TaskRecord, TaskRecordStoreInterface, InMemoryTaskRecordStore, TaskExecutor
from web_infra.state_machine import (
    BaseState,
    BaseEvent,
    BaseStatus,
    StartStopEvent,
    BaseStatusRouter,
    StateRouteParams,
    StateRouter,
    StateMachine,
    StateMachineEngine,
    StateMachineRegistry,
    StateMachineErrorCode,
)
from web_infra.monitoring import (
    PhaseTimer,
    init_ai_metrics,
    record_ai_call,
    record_ai_ttft,
    record_ai_duration,
    record_ai_tokens,
    record_ai_cost,
)
from web_infra.utils import (
    DateUtil,
    TimezoneConfig,
    SnowflakeUtil,
    snowflake_id,
    FileLock,
    DataUtil,
    MathUtil,
    TokenCounter,
    count_tokens,
    PdfRenderer,
)
from web_infra.application import Application, create_app

__version__ = "0.1.0"

__all__ = [
    # 响应与错误码
    "Result", "PageResult", "PageData",
    "ErrorCode", "ErrorCodeRegistry", "CommonErrorCode",
    "parse_category", "derive_http_status", "is_client_error", "is_retryable", "converge_error_code",
    "WebInfraException", "BizException", "ParamException", "PermException", "AuthException",
    "register_global_exception_handlers",
    # 上下文与日志
    "RequestContext", "RequestContextSnapshot", "generate_trace_id",
    "configure_logging", "get_logger", "mask",
    # 韧性
    "RetryConfig", "retry", "CircuitBreaker", "CircuitBreakerConfig", "CircuitBreakerState",
    "CircuitOpenError", "RateLimitConfig", "TokenBucketRateLimiter", "DistributedLock",
    # AI
    "ModelProviderInterface", "ModelProviderRegistry", "ChatRole", "FinishReason", "ChatMessage", "Usage",
    "ChatRequest", "ChatResponse", "ChatStreamChunk", "EmbeddingRequest", "EmbeddingResponse",
    "AiErrorCode", "ModelConfig", "ModelConfigStoreInterface", "DictModelConfigStore", "ModelConfigManager",
    "PromptTemplate", "PromptTemplateStoreInterface", "InMemoryPromptTemplateStore", "PromptTemplateFiller",
    "ContextWindowErrorParser", "ContextTruncator", "ContextWindowRetryPolicy",
    "DocumentChunkerInterface", "MarkdownChunker", "VectorStoreInterface", "InMemoryVectorStore",
    "EmbeddingProviderInterface", "RerankerInterface", "Retriever",
    "GuardAction", "GuardResult", "ContentGuardInterface", "RuleBasedContentGuard",
    "UsageRecord", "UsageRecordStoreInterface", "UsageAccounting", "AICache", "PromptAssembler",
    "ConnectionPoolConfig", "ConnectionPoolManager", "ConcurrencyGuard",
    "QuotaConfig", "QuotaCounter", "QuotaStoreInterface", "InMemoryQuotaStore", "QuotaManager",
    "RouteEntry", "ModelGatewayConfig", "ModelRouter", "ModelGateway",
    # Web
    "RequestContextMiddleware", "TraceIdMiddleware", "BigIntJSONResponse", "setup_cors",
    "LoggingMiddleware", "setup_logging_middleware", "register_health_endpoints",
    "format_sse", "format_sse_error", "sse_response",
    "IdempotencyResult", "IdempotencyStoreInterface", "InMemoryIdempotencyStore",
    "RedisIdempotencyStore", "IdempotencyMiddleware", "AuthMiddleware", "RateLimitMiddleware",
    # 配置
    "ConfigSourceInterface", "ConfigError", "EnvConfigSource", "DictConfigSource", "JsonFileConfigSource",
    "YamlConfigSource", "CompositeConfigSource", "Settings", "BaseConfig", "ConfigClientInterface",
    "NacosConfigClient", "NacosConfigLoader", "NacosProperties",
    # 常量
    "AuthConstant", "CacheKeyBuilder", "InfraConstant", "ParamConstant", "SysConstant", "BizConstant",
    # 缓存
    "KeyBuilder", "TenantKeyBuilder", "CacheBackendInterface", "CacheConfig", "MemoryCacheBackend",
    # 数据库（依赖 sqlalchemy/redis/mongo 的实现名不在 __all__，保证最小安装 `from web_infra import *`
    # 不触发惰性导入；需用时显式导入，如 from web_infra import MySQLConfig / Base）
    "DatabaseConfig", "PageQuery", "SqliteSessionFactory", "DatabaseSessionInterface", "DatabaseFactoryInterface",
    "SessionScopeMixin", "provide_db_session",
    "MySQLConnectionSettings", "release_session_connection", "connection_released",
    "TenantGuard", "DatabaseRouterInterface", "TenantDatabaseRouter",
    # 消息队列
    "MqConfig", "Message", "MessagePublisherInterface", "MessageConsumerInterface", "InMemoryMessageQueue",
    "RocketMqConfig", "RocketMqPublisher",
    "MessageIdempotencyStoreInterface", "InMemoryMessageIdempotencyStore", "RedisMessageIdempotencyStore", "IdempotentConsumer",
    "OutboxStatus", "OutboxRecord", "OutboxStoreInterface", "InMemoryOutboxStore", "OutboxPublisher", "OutboxCleaner",
    # 对象存储
    "StorageConfig", "ObjectStorageInterface", "LocalObjectStorage", "MinioStorageConfig", "MinioObjectStorage",
    "UploadStatus", "UploadTask", "UploadStoreInterface", "InMemoryUploadStore",
    "PartStorageInterface", "LocalPartStorage", "MinioPartStorage", "MultipartUploadService",
    # 支付
    "PaymentGateway", "PaymentCallbackVerifier", "PaymentCallbackHandler",
    "PaymentCallbackDispatcher", "PaymentGatewayRegistry",
    "PaymentPrepayRequest", "PaymentPrepayResponse", "PaymentOrder",
    "PaymentRefundRequest", "PaymentRefundResponse", "PaymentCallback",
    "PaymentScene", "PaymentStatus", "RefundStatus", "PaymentErrorCode", "PaymentConfig",
    # 定时调度
    "ScheduledTask", "TaskScheduler",
    # 服务注册发现与负载均衡
    "ServiceInstance", "ServiceRegistryInterface", "NacosDiscoveryClient", "NacosRegistration", "InMemoryServiceRegistry",
    "LoadBalancerInterface", "RandomBalancer", "RoundRobinBalancer", "WeightedRoundRobinBalancer", "FeignClient",
    "FeignClientConfig", "build_feign_client",
    "default_service_fallback",
    # 安全
    "JWTUtil", "TokenVerifyStatus", "PasswordEncoder", "SecureConfigLoader", "PrivacyGuard",
    "PiiResult", "PiiMatch", "CaptchaStoreInterface", "InMemoryCaptchaStore", "RedisCaptchaStore",
    "CaptchaService", "LoginFailLockService", "PermissionGuard",
    "OAuth2Client", "OAuth2ClientRegistry", "InMemoryOAuth2ClientRegistry", "OAuth2TokenService",
    "JwtTokenStore", "InMemoryJwtTokenStore", "RedisJwtTokenStore",
    "JwtKeyProvider", "EnvJwtKeyProvider",
    "SocialPlatform", "SocialAccessToken", "SocialUserInfo", "SocialBinding",
    "SocialBindingStore", "InMemorySocialBindingStore", "SocialPlatformRegistry",
    "DemoSocialPlatform", "SocialLoginResult", "SocialLoginService",
    # 异步任务
    "TaskStatus", "TaskRecord", "TaskRecordStoreInterface", "InMemoryTaskRecordStore", "TaskExecutor",
    # 通用状态机
    "BaseState", "BaseEvent", "BaseStatus", "StartStopEvent", "BaseStatusRouter",
    "StateRouteParams", "StateRouter", "StateMachine", "StateMachineEngine",
    "StateMachineRegistry", "StateMachineErrorCode",
    # 监控与工具
    "PhaseTimer", "init_ai_metrics", "record_ai_call", "record_ai_ttft", "record_ai_duration",
    "record_ai_tokens", "record_ai_cost",
    "DateUtil", "TimezoneConfig", "SnowflakeUtil", "snowflake_id", "FileLock",
    "DataUtil", "MathUtil", "TokenCounter", "count_tokens", "PdfRenderer",
    # 应用启动器
    "Application", "create_app",
]

# 惰性导出名集合（db 相关、依赖 sqlalchemy/redis/mongo；最小安装下 `import web_infra` 不触发，
# 首次访问该名字时才从 web_infra.db 延迟导入，未安装对应依赖时抛 ImportError）
_LAZY_DB_EXPORTS: frozenset[str] = frozenset({
    "Base",
    "MySQLConfig",
    "MySQLDatabase",
    "MongoDBConfig",
    "RedisConfig",
    "RedisCacheBackend",
    "TenantAwareMixin",
    "TenantQueryFilter",
    "DatabaseManager",
})


def __getattr__(name: str) -> object:
    """惰性导出 db 相关名字：首次访问时从 web_infra.db 导入并缓存到模块命名空间。

    :param name: 访问的属性名
    :return: web_infra.db 中同名导出对象
    :raises AttributeError: 未匹配的属性名
    """
    if name in _LAZY_DB_EXPORTS:
        value = getattr(import_module("web_infra.db"), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# 惰性导出名 -> 其依赖的第三方包（已安装时该名字纳入 __all__，`import *` 全量导出）
_LAZY_ALL_REQUIRES: dict[str, tuple[str, ...]] = {
    "Base": ("sqlalchemy",),
    "MySQLConfig": ("sqlalchemy",),
    "MySQLDatabase": ("sqlalchemy",),
    "MongoDBConfig": ("pymongo", "beanie"),
    "RedisConfig": ("redis",),
    "RedisCacheBackend": ("redis",),
    "TenantAwareMixin": ("sqlalchemy",),
    "TenantQueryFilter": ("sqlalchemy",),
    "DatabaseManager": ("sqlalchemy",),
}


def _extend_all_with_installed() -> None:
    """按已安装的可选依赖动态扩展 __all__（import * 全量导出）。

    最小安装（未装 sqlalchemy/redis/pymongo/beanie）时惰性名不进 __all__，
    `from web_infra import *` 不触发惰性导入；安装对应 extras 后自动纳入，
    使非最小安装下 `import *` 可导出全部能力（ORM/Redis/Mongo 组件）。
    检测用 importlib.util.find_spec（不实际导入，避免触发惰性加载）。
    """
    import importlib.util

    for name, packages in _LAZY_ALL_REQUIRES.items():
        try:
            installed = all(importlib.util.find_spec(pkg) is not None for pkg in packages)
        except (ImportError, ValueError):
            installed = False
        if installed and name not in __all__:
            __all__.append(name)


_extend_all_with_installed()
