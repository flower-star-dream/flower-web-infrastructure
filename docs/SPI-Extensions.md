# flower web 通用框架 SPI 扩展点文档

> 本文档汇总本框架预留的全部 SPI（Service Provider Interface）扩展点：接口定位、方法契约、默认实现与扩展接入方式。业务侧遵循本文档接入自定义实现，无需改动框架代码，防止技术栈锁定。
>
> 上位规范：《web系统后端通用架构规范》§3.3 扩展点（SPI）机制、AI 与大模型扩展规范 §2.1/§5.5。

## 目录

- [1. SPI 机制概述](#1-spi-机制概述)
  - [1.1 设计原则](#11-设计原则)
  - [1.2 两种接入方式](#12-两种接入方式)
  - [1.3 接口文件位置](#13-接口文件位置)
- [2. 接口总览](#2-接口总览)
- [3. 配置模块（config）](#3-配置模块config)
  - [3.1 ConfigClientInterface —— 配置中心通用接口](#31-configclientinterface--配置中心通用接口)
  - [3.2 ConfigSourceInterface —— 统一配置源接口](#32-configsourceinterface--统一配置源接口)
- [4. 数据库模块（db）](#4-数据库模块db)
  - [4.1 DatabaseSessionInterface —— 通用数据库会话接口](#41-databasesessioninterface--通用数据库会话接口)
  - [4.2 DatabaseFactoryInterface —— 通用数据库工厂接口](#42-databasefactoryinterface--通用数据库工厂接口)
  - [4.2.1 自定义数据库接入与使用示例（两种方式）](#421-自定义数据库接入与使用示例两种方式)
  - [4.3 DatabaseRouterInterface —— 数据库路由接口](#43-databaserouterinterface--数据库路由接口)
- [5. 注册发现模块（registry）](#5-注册发现模块registry)
  - [5.1 ServiceRegistryInterface —— 服务注册发现通用接口](#51-serviceregistryinterface--服务注册发现通用接口)
- [6. 负载均衡模块（loadbalance）](#6-负载均衡模块loadbalance)
  - [6.1 LoadBalancerInterface —— 负载均衡器抽象接口](#61-loadbalancerinterface--负载均衡器抽象接口)
- [7. AI 模块（ai）](#7-ai-模块ai)
  - [7.1 ModelProviderInterface —— 模型供应商接口（Provider SPI）](#71-modelproviderinterface--模型供应商接口provider-spi)
  - [7.2 ModelConfigStoreInterface —— 模型配置来源接口](#72-modelconfigstoreinterface--模型配置来源接口)
  - [7.3 ContentGuardInterface —— 内容安全审核接口](#73-contentguardinterface--内容安全审核接口)
  - [7.4 QuotaStoreInterface —— 配额计数存储接口](#74-quotastoreinterface--配额计数存储接口)
  - [7.5 PromptTemplateStoreInterface —— 提示词模板存储接口](#75-prompttemplatestoreinterface--提示词模板存储接口)
  - [7.6 UsageRecordStoreInterface —— 用量记录存储接口](#76-usagerecordstoreinterface--用量记录存储接口)
  - [7.7 VectorStoreInterface —— 向量存储接口](#77-vectorstoreinterface--向量存储接口)
  - [7.8 EmbeddingProviderInterface —— 向量嵌入供应商接口](#78-embeddingproviderinterface--向量嵌入供应商接口)
  - [7.9 DocumentChunkerInterface —— 文档切片接口](#79-documentchunkerinterface--文档切片接口)
  - [7.10 RerankerInterface —— 检索结果重排接口](#710-rerankerinterface--检索结果重排接口)
  - [7.11 ModelProviderFactory.register_factory —— 供应商构建器注册点](#711-modelproviderfactoryregisterfactory--供应商构建器注册点)
  - [7.12 ModelAccessPolicy —— 模型/能力使用权限策略（SPI）](#712-modelaccesspolicy--模型能力使用权限策略spi)
- [8. 缓存模块（cache）](#8-缓存模块cache)
  - [8.1 CacheBackendInterface —— 缓存后端统一抽象接口](#81-cachebackendinterface--缓存后端统一抽象接口)
- [9. 消息队列模块（mq）](#9-消息队列模块mq)
  - [9.1 MessagePublisherInterface —— 消息发布者接口](#91-messagepublisherinterface--消息发布者接口)
  - [9.2 MessageConsumerInterface —— 消息消费者接口](#92-messageconsumerinterface--消息消费者接口)
  - [9.3 MessageIdempotencyStoreInterface —— 消息幂等键存储接口](#93-messageidempotencystoreinterface--消息幂等键存储接口)
  - [9.4 OutboxStoreInterface —— Outbox 存储接口](#94-outboxstoreinterface--outbox-存储接口)
  - [9.5 MessageQueueSelector —— 消息分区选择器（SPI）](#95-messagequeueselector--消息分区选择器spi)
- [10. 监控模块（monitoring）](#10-监控模块monitoring)
  - [10.1 MetricGroupProviderInterface —— 自定义指标分组 SPI 接口](#101-metricgroupproviderinterface--自定义指标分组-spi-接口)
  - [10.2 ComponentMetricsCollector —— 组件指标采集器抽象基类](#102-componentmetricscollector--组件指标采集器抽象基类)
  - [10.3 ThreadPoolMetrics —— 线程池指标注册表（SPI 风格）](#103-threadpoolmetrics--线程池指标注册表spi-风格)
- [11. 安全模块（security）](#11-安全模块security)
  - [11.1 CaptchaStoreInterface —— 验证码存储接口](#111-captchastoreinterface--验证码存储接口)
  - [11.2 SocialPlatform —— 三方平台适配接口](#112-socialplatform--三方平台适配接口)
  - [11.3 SocialBindingStore —— 三方账号绑定存储接口](#113-socialbindingstore--三方账号绑定存储接口)
  - [11.4 JwtTokenStore —— JWT Token 状态存储接口](#114-jwttokenstore--jwt-token-状态存储接口)
  - [11.5 JwtKeyProvider —— JWT 签名密钥/算法接口](#115-jwtkeyprovider--jwt-签名密钥算法接口)
- [12. 存储模块（storage）](#12-存储模块storage)
  - [12.1 ObjectStorageInterface —— 对象存储统一抽象接口](#121-objectstorageinterface--对象存储统一抽象接口)
  - [12.2 PartStorageInterface —— 分片存储接口](#122-partstorageinterface--分片存储接口)
  - [12.3 UploadStoreInterface —— 分片上传任务存储接口](#123-uploadstoreinterface--分片上传任务存储接口)
- [13. 异步任务模块（task）](#13-异步任务模块task)
  - [13.1 TaskRecordStoreInterface —— 任务记录存储接口](#131-taskrecordstoreinterface--任务记录存储接口)
- [14. Web 模块（web）](#14-web-模块web)
  - [14.1 IdempotencyStoreInterface —— API 幂等键存储接口](#141-idempotencystoreinterface--api-幂等键存储接口)
- [15. 支付模块（payment）](#15-支付模块payment)
- [16. 日志模块（logging）](#16-日志模块logging)
  - [16.1 LogSinkInterface —— 日志输出通道接口](#161-logsinkinterface--日志输出通道接口)
- [17. 扩展接入指引](#17-扩展接入指引)
  - [17.1 接入步骤](#171-接入步骤)
  - [17.2 三方平台接入步骤（参照 `DemoSocialPlatform`）](#172-三方平台接入步骤参照-demosocialplatform)
  - [17.3 自定义模型供应商示例（参照 `OpenAICompatibleProvider`）](#173-自定义模型供应商示例参照-openaicompatibleprovider)
  - [17.4 自定义对象存储实现示例（参照 `MinioStorage`）](#174-自定义对象存储实现示例参照-miniostorage)
  - [17.5 自定义指标分组示例（参照 `metric_group_provider_interface.py`）](#175-自定义指标分组示例参照-metricgroupproviderinterfacepy)
  - [17.6 常见替换对照](#176-常见替换对照)
- [18. 能力注册表（capability）](#18-能力注册表capability)
  - [18.1 能力契约与内置依赖图](#181-能力契约与内置依赖图)
  - [18.2 依赖解析（resolve）与装配校验（validate）](#182-依赖解析resolve与装配校验validate)
  - [18.3 启用能力（enable / app.capabilities.enabled）](#183-启用能力enable--appcapabilitiesenabled)
  - [18.4 业务扩展自定义能力](#184-业务扩展自定义能力)
- [19. 统一扩展注册器（extension）](#19-统一扩展注册器extension)
  - [19.1 定位与边界](#191-定位与边界)
  - [19.2 扩展点契约（ExtensionPoint）](#192-扩展点契约extensionpoint)
  - [19.3 注册（同名默认拒绝）](#193-注册同名默认拒绝)
  - [19.4 依赖解析（resolve）与装配校验（validate）](#194-依赖解析resolve与装配校验validate)
  - [19.5 配置驱动启用（app.extensions.enabled）](#195-配置驱动启用appextensionsenabled)
  - [19.6 生命周期编排（startup 拓扑序 / 停机逆序）](#196-生命周期编排startup-拓扑序--停机逆序)
  - [19.7 接入示例（业务插件）](#197-接入示例业务插件)
- [20. 搜索引擎模块（search）](#20-搜索引擎模块search)
  - [20.1 SearchEngineInterface —— 全文搜索引擎接口](#201-searchengineinterface--全文搜索引擎接口)
  - [20.2 默认实现与生产实现](#202-默认实现与生产实现)
  - [20.3 向量检索接入（ElasticsearchVectorStore）](#203-向量检索接入elasticsearchvectorstore)
  - [20.4 错误码与配置](#204-错误码与配置)
- [21. 维护指南](#21-维护指南)

## 1. SPI 机制概述

### 1.1 设计原则

| 约束项 | 要求 |
| ---- | ---- |
| 扩展方式 | 定义扩展接口承载差异化逻辑，禁止业务代码 if-else 硬编码分支扩展 |
| 注册方式 | 统一注册机制（注册表/配置声明），显式注册，扩展不散落 |
| 默认实现 | 每个扩展点必须提供默认实现，核心功能不因扩展缺失而失效 |
| 接口类型 | `Protocol`（结构子类型，无需继承即可满足）或 `ABC`（需继承实现），见各接口说明 |

### 1.2 两种接入方式

- **注册表注册**：实现接口后调用对应注册表 `register()`（如 `ModelProviderRegistry`、`MetricGroupProviderRegistry`）。
- **配置声明装配**：通过 yml 配置声明（如 `app.ai.models` 清单经 `ModelAutoRegistrar` 自动注册），业务代码无需手动注册。

### 1.3 接口文件位置

全部接口位于 `src/web_infra` 各模块目录下，命名统一为 `<职责>_interface.py`，文中均给出相对路径。

## 2. 接口总览

| 模块 | 接口 | 类型 | 默认实现 | 多实例建议实现 |
| ---- | ---- | ---- | ---- | ---- |
| config | `ConfigClientInterface` | Protocol | 无（Nacos 内置实现） | Nacos/Apollo |
| config | `ConfigSourceInterface` | Protocol | `CompositeConfigSource` | 配置中心适配 |
| db | `DatabaseSessionInterface` | Protocol | `SqlAlchemyDatabaseSession` / `SqliteSession` | PG/其他 ORM |
| db | `DatabaseFactoryInterface` | Protocol | `SqliteSessionFactory` / `MySQLDatabase`（`DatabaseRegistry` 按 `app.db.type` 或 `app.db.instances` 装配） | PG 工厂（register 接入） |
| db | `DatabaseRouterInterface` | ABC | `TenantDatabaseRouter` | 自定义路由策略 |
| db | `MongoSessionInterface` | Protocol | `BeanieMongoSession`（集合级文档 CRUD） | 其他文档数据库 |
| db | `MongoDatabaseFactoryInterface` | Protocol | `MongoDatabase`（Beanie + PyMongo，`MongoDatabaseRegistry` 按 `app.mongo.type` 装配，内置 `beanie`） | 其他文档数据库工厂（register 接入） |
| registry | `ServiceRegistryInterface` | Protocol | `InMemoryServiceRegistry` | Nacos/Eureka/Consul |
| loadbalance | `LoadBalancerInterface` | ABC | `RandomBalancer` / `RoundRobinBalancer` / `WeightedRoundRobinBalancer` | 自定义策略 |
| ai | `ModelProviderInterface` | ABC | `OpenAICompatibleProvider` | Anthropic/DeepSeek 等 |
| ai | `ModelConfigStoreInterface` | Protocol | `DictModelConfigStore`（yml）/ `SqlAlchemyModelConfigStore`（数据库 ai_model_config 表，数据源跟随 app.db.type） | 配置中心（`ModelConfigStoreRegistry.register` 接入） |
| ai | `ContentGuardInterface` | ABC | `RuleBasedContentGuard` | 第三方审核服务 |
| ai | `QuotaStoreInterface` | ABC | `InMemoryQuotaStore` | Redis（INCR + TTL 窗口） |
| ai | `PromptTemplateStoreInterface` | ABC | `InMemoryPromptTemplateStore` | 数据库 prompt_templates 表 |
| ai | `UsageRecordStoreInterface` | ABC | 结构化日志输出 | 数据库（计费/审计） |
| ai | `VectorStoreInterface` | ABC | `InMemoryVectorStore` | FAISS/Milvus/`ElasticsearchVectorStore`（dense_vector + kNN，es extra） |
| ai | `EmbeddingProviderInterface` | ABC | `HashEmbeddingProvider`（稳定哈希本地嵌入） | bge-m3/OpenAI 等 |
| ai | `DocumentChunkerInterface` | ABC | `MarkdownChunker` | 按文档类型扩展 |
| ai | `RerankerInterface` | ABC | `IdentityReranker` | CrossEncoder 等 |
| ai | `ModelProviderFactory.register_factory` | 注册表 | OpenAI 兼容回落 | 自定义协议工厂 |
| ai | `ModelAccessPolicy` | ABC | `AllowAllModelAccessPolicy` | RBAC 权限策略 |
| cache | `CacheBackendInterface` | Protocol | `MemoryCacheBackend`（`CacheBackendRegistry` 按 `app.cache.type` 装配） | Redis/自定义（register 接入） |
| mq | `MessagePublisherInterface` | Protocol | `InMemoryMessageQueue`（`MessageQueueRegistry` 按 `app.mq.type` 装配） | RocketMQ/Kafka（register 接入） |
| mq | `MessageConsumerInterface` | Protocol | `InMemoryMessageQueue` | RocketMQ/Kafka |
| mq | `MessageIdempotencyStoreInterface` | Protocol | `InMemoryMessageIdempotencyStore` | Redis SETNX / DB 唯一约束 |
| mq | `MessageQueueSelector` | ABC | `HashMessageQueueSelector` | 自定义分区策略 |
| mq | `OutboxStoreInterface` | Protocol | `InMemoryOutboxStore` | MySQL（DDL 见 db/init/ddl/001-mq-init-ddl.sql） |
| monitoring | `MetricGroupProviderInterface` | ABC | `DefaultMetricGroupProvider` | - |
| monitoring | `ComponentMetricsCollector` | ABC | 内置组件各自子类 | 自定义组件指标 |
| monitoring | `ThreadPoolMetrics` | 注册表 | 内置 | - |
| security | `CaptchaStoreInterface` | ABC | `InMemoryCaptchaStore` | Redis |
| storage | `ObjectStorageInterface` | Protocol | `LocalObjectStorage`（`ObjectStorageRegistry` 按 `app.storage.type` 装配） | MinIO/云 OSS/S3（register 接入） |
| storage | `PartStorageInterface` | Protocol | `LocalPartStorage` | MinIO 分段上传 |
| storage | `UploadStoreInterface` | Protocol | `InMemoryUploadStore` | Redis/MySQL |
| task | `TaskRecordStoreInterface` | ABC | `InMemoryTaskRecordStore` | MySQL（乐观锁） |
| web | `IdempotencyStoreInterface` | Protocol | `InMemoryIdempotencyStore` | Redis/DB |
| security | `SocialPlatform` | Protocol | `DemoSocialPlatform` | 微信/GitHub/钉钉等 |
| registry | `ServiceRegistryInterface` | Protocol | `InMemoryServiceRegistry`（`ServiceDiscoveryRegistry` 按 `app.registry.type` 装配） | Nacos/Eureka/Consul（register 接入） |
| security | `SocialBindingStore` | Protocol | `InMemorySocialBindingStore` | Redis/MySQL |
| security | `JwtTokenStore` | Protocol | `InMemoryJwtTokenStore` / `RedisJwtTokenStore` | 共享存储 |
| security | `JwtKeyProvider` | Protocol | `EnvJwtKeyProvider` | RS256/KMS 托管 |
| payment | `PaymentGateway` | Protocol | `InMemoryPaymentGateway` | 微信/支付宝等渠道 |
| payment | `PaymentCallbackVerifier` | Protocol | `InMemoryPaymentCallbackVerifier` | 微信回调验签（平台证书/公钥） |
| payment | `PaymentCallbackHandler` | ABC | 无（业务必选） | 支付/退款回调业务处理 |
| logging | `LogSinkInterface` | Protocol | `ConsoleLogSink` / `FileLogSink`（`LogSinkRegistry` 按 `app.logging.sinks` 装配） | 远端日志平台/消息队列等自定义通道 |
| search | `SearchEngineInterface` | Protocol | `InMemorySearchEngine`（`SearchEngineRegistry` 按 `app.search.type` 装配） | Elasticsearch（es extra）/自研（register 接入） |

## 3. 配置模块（config）

### 3.1 ConfigClientInterface —— 配置中心通用接口

- 文件：`src/web_infra/config/config_client_interface.py`
- 定位：屏蔽 Nacos/Apollo 等配置中心差异，用户可自行实现替换，防止技术栈锁定（规范 §15.2 配置安全）。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async get_config(data_id: str, group: str \| None = None) -> str` | 拉取指定配置内容（字符串），不存在返回空字符串 |
| `get_config_sync(data_id: str, group: str \| None = None) -> str` | 同步拉取配置（仅无运行中事件循环的上下文，如应用启动阶段；事件循环内请用异步方法） |
| `async close() -> None` | 释放底层资源 |

- 默认实现：`NacosConfigClient`（`nacos_config_client.py`，官方 nacos-sdk-python v2，gRPC 协议；需安装 `nacos` extras）。

### 3.2 ConfigSourceInterface —— 统一配置源接口

- 文件：`src/web_infra/config/config_source_interface.py`
- 定位：应用代码只依赖该接口，屏蔽本地文件/配置中心差异。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `get(key: str, default: Any = None) -> Any` | 按 key 读取配置，不存在时返回 default |
| `contains(key: str) -> bool` | 判断配置项是否存在 |

- 默认实现：`CompositeConfigSource`（按优先级聚合 yml/env/json 等本地源），亦可组合 `NacosConfigLoader`。

## 4. 数据库模块（db）

### 4.1 DatabaseSessionInterface —— 通用数据库会话接口

- 文件：`src/web_infra/db/database_session_interface.py`
- 定位：一次数据库交互的最小单元，屏蔽 MySQL/PostgreSQL/SQLite 等差异；SQL 使用命名参数（`:name`）+ 参数字典，各实现自行适配驱动占位符（规范 §10 数据访问）。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async execute(sql: str, params: Any = None) -> int` | 执行写操作，返回影响行数 |
| `async query_one(sql: str, params: Any = None) -> dict[str, Any] \| None` | 查询单行，返回字典或 None |
| `async query_all(sql: str, params: Any = None) -> list[dict[str, Any]]` | 查询多行，返回字典列表 |
| `async commit() -> None` | 提交事务 |
| `async rollback() -> None` | 回滚事务 |
| `async close() -> None` | 关闭会话（归还连接） |

- 默认实现：`SqlAlchemyDatabaseSession`（`sqlalchemy_database_session.py`）、`SqliteSession`（`sqlite_session.py`）。

### 4.2 DatabaseFactoryInterface —— 通用数据库工厂接口

- 文件：`src/web_infra/db/database_factory_interface.py`
- 定位：用户扩展其他数据库（如 PG）时实现本接口即可接入框架（规范 §3/§10）。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async create_session() -> DatabaseSessionInterface` | 创建通用数据库会话 |
| `session() -> AsyncContextManager[DatabaseSessionInterface]` | 异步上下文管理器：进入创建会话，退出自动提交（异常回滚）并关闭，业务无需 try/finally |
| `async close() -> None` | 关闭连接池/底层资源 |
| `async health_check() -> bool` | 健康检查 |

- 默认实现：`SqliteSessionFactory`（`sqlite_session_factory.py`）；MySQL 侧提供 `MySQLDatabase`/`DatabaseManager` 等构建配套。
- 装配：`DatabaseRegistry`（`database_registry.py`）按 `app.db.type` 单源按名装配（内置 `mysql`/`sqlite`，自定义如 PostgreSQL 经 `register(name, factory)` 接入，工厂签名 `(实例连接参数 dict) -> DatabaseFactoryInterface`）；混合多数据源（`app.db.instances`，每实例带 `type` 字段）装配为 `DatabaseManager` 按名/租户路由，支持 MySQL/PostgreSQL 等不同数据库并存；`app.db.mysql.instances`（多租户独立库）向后兼容缺省回落 mysql。未注册 type 启动期快速失败（`ConfigError`）。

#### 4.2.1 自定义数据库接入与使用示例（两种方式）

> 场景：框架内置 MySQL/SQLite，接入 PostgreSQL 等其他数据库。以下以 PostgreSQL 为例（依赖 `sqlalchemy` + `asyncpg`，业务侧自行安装 asyncpg）。

**第一步：实现 `DatabaseFactoryInterface` 并注册进 `DatabaseRegistry`**

```python
# my_pg_database.py
"""PostgreSQL 数据库实现（自定义数据库接入示例）

@Author: 花海
@Date: 2026/08/17
@Description: 基于 SQLAlchemy asyncpg 的 PostgreSQL 数据库工厂（DatabaseFactoryInterface 最小契约
              + 可选 session_factory 能力），经 DatabaseRegistry.register 接入框架装配。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from web_infra.capabilities.db import DatabaseRegistry


class PgDatabase:
    """PostgreSQL 数据库工厂（DatabaseFactoryInterface：create_session/session/close/health_check）"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "app",
        username: str = "postgres",
        password: str = "",
    ) -> None:
        self._engine = create_async_engine(
            f"postgresql+asyncpg://{username}:{password}@{host}:{port}/{database}"
        )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def session_factory(self) -> Any:
        """SQLAlchemy 异步会话工厂（可选能力：供 SqlAlchemyModelConfigStore 等框架组件复用）"""
        return self._session_factory

    async def create_session(self) -> Any:
        """创建通用数据库会话"""
        return await self._session_factory()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[Any, None]:
        """异步上下文管理器：进入创建会话，退出自动提交（异常回滚）并关闭"""
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def close(self) -> None:
        """关闭连接池/底层资源"""
        await self._engine.dispose()

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            async with self._session_factory() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False


def build_pg(params: dict[str, Any]) -> PgDatabase:
    """数据库工厂（DatabaseRegistry 工厂签名）：入参为 app.db.pg 段或 app.db.instances 实例参数"""
    return PgDatabase(**{k: v for k, v in params.items() if k != "datasource_name"})


# 注册进 DatabaseRegistry（模块导入即注册，幂等；应用入口 import my_pg_database 即生效）
DatabaseRegistry.register("pg", build_pg)
```

**方式一：单源替换**（整个应用数据库替换为 PostgreSQL，`app.db.type: pg`）

```yaml
# application.yml
db:
  type: pg
  pg:                       # app.db.pg 段 = DatabaseRegistry 工厂入参
    host: localhost
    port: 5432
    database: app
    username: postgres
    password: ${APP_DB_PG_PASSWORD:}
```

```python
# 应用入口（create_app 前先导入注册模块）
import my_pg_database  # noqa: F401  触发 DatabaseRegistry.register("pg", ...)

db = app.state.db                 # PgDatabase 实例
async with db.session() as session:
    ...
```

**方式二：多源并存**（同一应用 MySQL 与 PostgreSQL 共存，`app.db.instances` 每实例带 `type`）

```yaml
# application.yml
db:
  instances:
    order:    { type: mysql, host: 127.0.0.1, port: 3306, database: order_db }   # 订单库 MySQL
    audit:    { type: pg,    host: localhost, port: 5432, database: audit_db }   # 审计库 PostgreSQL
```

```python
import my_pg_database  # noqa: F401

db = app.state.db                 # DatabaseManager：按名获取任意数据源
async with db.get("order").session() as session:   # MySQL
    ...
async with db.get("audit").session() as session:   # PostgreSQL
    ...
```

> **同类型多库同样适用**：`app.db.instances` 实例未带 `type` 时缺省回落 `mysql`（或显式写 `type: mysql`），
> 多个实例均为同一类型数据库（如订单/库存各自独立 MySQL 库）时同样装配为 `DatabaseManager` 按名获取。

**可选能力**（非 DatabaseFactoryInterface 必需，按需实现即可被框架对应功能识别）：
- `session_factory`（SQLAlchemy 异步会话工厂）：供 `SqlAlchemyModelConfigStore`（AI 模型配置 `store.type=db`）等复用同库；
- `install_tenant_filter(tenant_filter)`：多租户（`app.tenant.enabled=true`）时挂载租户条件过滤器；
- `orm_session()`：SQLAlchemy ORM 会话上下文管理器（`DatabaseManager.orm_session` 委托调用）。

### 4.3 DatabaseRouterInterface —— 数据库路由接口

- 文件：`src/web_infra/db/database_router.py`
- 定位：多数据源动态路由（多租户规范 §4：独立库/Schema 模式共享连接池 + 动态路由），按租户标识路由到对应数据源。
- 类型：`ABC`

| 方法 | 说明 |
| ---- | ---- |
| `route(tenant_id: str) -> str` | 按租户标识解析目标数据源名 |
| `unregister(tenant_id: str) -> None` | 注销租户显式映射（无映射的模板租户静默，多租户规范 §4：租户删除/归档后 24h 内注销路由） |
| `registered_tenants() -> list[str]` | 返回已注册显式映射的租户清单（注销审计用） |

- 默认实现：`TenantDatabaseRouter`——显式映射优先，未命中按命名模板 `tenant_{tenant_id}` 生成；`unregister` 仅移除显式映射。

### 4.4 MongoSessionInterface —— MongoDB 通用会话接口

- 文件：`src/web_infra/db/mongo_session_interface.py`
- 定位：MongoDB 功能 SPI 化（与关系型 DatabaseSessionInterface 对齐），一次文档数据库交互的最小单元。
  契约采用**集合级通用形态**（`collection` 名 + dict 文档/filter，返回值统一归一化），
  屏蔽 Beanie / PyMongo / 其他 ODM 差异；filter / update / pipeline 沿用 MongoDB 查询语法。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async insert_one(collection, document) -> str` | 插入单条文档，返回 `_id` 字符串形式 |
| `async insert_many(collection, documents) -> list[str]` | 批量插入，返回 `_id` 字符串列表 |
| `async find_one(collection, filter, projection, sort) -> dict \| None` | 查询单条文档，返回 dict 或 None |
| `async find_many(collection, filter, projection, sort, skip, limit) -> list[dict]` | 查询多条文档（limit<=0 不限制数量） |
| `async update_one(collection, filter, update, upsert, array_filters) -> int` | 更新单条，返回实际修改条数 |
| `async update_many(collection, filter, update, upsert, array_filters) -> int` | 更新多条，返回实际修改条数 |
| `async replace_one(collection, filter, replacement, upsert) -> int` | 替换单条，返回实际修改条数 |
| `async delete_one(collection, filter) -> int` | 删除单条，返回删除条数 |
| `async delete_many(collection, filter) -> int` | 删除多条，返回删除条数 |
| `async count(collection, filter) -> int` | 统计匹配文档条数 |
| `async aggregate(collection, pipeline) -> list[dict]` | 聚合管道查询 |
| `async distinct(collection, key, filter) -> list[Any]` | 指定字段去重取值 |
| `async create_index(collection, keys, name, unique) -> str` | 创建索引，返回索引名 |
| `async commit() / rollback() / close()` | 事务提交/回滚（非事务会话为空操作）/ 关闭会话 |

### 4.5 MongoDatabaseFactoryInterface —— MongoDB 通用数据库工厂接口

- 文件：`src/web_infra/db/mongo_database_factory_interface.py`
- 定位：MongoDB 数据库工厂 SPI 扩展点（与关系型 DatabaseFactoryInterface 对齐）。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async create_session() -> MongoSessionInterface` | 创建通用 MongoDB 会话 |
| `session() -> AsyncContextManager[MongoSessionInterface]` | 异步上下文管理器：进入创建会话，退出自动提交（异常回滚）并关闭 |
| `async close() -> None` | 关闭客户端连接/释放底层资源 |
| `async health_check() -> bool` | 健康检查（ping） |

**可选能力**（非必需，按需实现即可被框架对应功能识别）：
- `register_document_models(models)`：注册 Beanie Document 模型并初始化 ODM（业务模型入口；未注册时仅集合级访问，纯 PyMongo 也可用）；
- `transaction()`：多文档事务上下文（需 MongoDB 副本集；事务内会话所有操作自动携带事务 session）；
- `get_database()` / `get_collection(name)`：原生访问入口（业务需要驱动级能力时使用）；
- `update_pool_metrics()`：刷新连接池运行指标（/metrics 抓取前调用）。

### 4.6 MongoDatabaseRegistry —— MongoDB 数据库注册表与默认实现（Beanie）

- 文件：`src/web_infra/db/mongo_database_registry.py`
- 定位：按 type 名注册/查询 `MongoDatabaseFactoryInterface` 工厂，装配期（`app.mongo.type`）按名实例化；
  内置 **`beanie`** 默认实现（`MongoDatabase` = `MongoDBConfig` 连接管理 + `BeanieMongoSession` 集合级会话，Beanie + PyMongo），
  未注册的 `app.mongo.type` 启动期快速失败（ConfigError）。
- 注册方式：`MongoDatabaseRegistry.register(name, factory)`（模块导入即注册，幂等；同名覆盖）。
- 工厂签名：入参为 `app.mongo` 段连接参数（排除 `enabled`/`type`）。

**装配与使用**（`app.mongo.enabled=true` 时经 `MongoDatabaseRegistry` 按 `app.mongo.type` 装配为 `app.state.mongo`）：

```yaml
# application.yml
mongo:
  enabled: true
  type: beanie            # MongoDatabaseRegistry 按名装配（内置 beanie 默认实现）
  url: mongodb://localhost:27017
  database: app
  username: ${APP_MONGO_USERNAME:}
  password: ${APP_MONGO_PASSWORD:}
```

```python
# 通用会话（集合级契约，业务只依赖 MongoSessionInterface，屏蔽 Beanie/PyMongo 差异）
mongo = app.state.mongo
async with mongo.session() as session:
    order_id = await session.insert_one("orders", {"user_id": 1, "amount": 99.5})
    order = await session.find_one("orders", {"_id": order_id})

# 注册 Beanie Document 模型（生命周期钩子内调用，可多次追加；ODM 初始化后可用 Document 类方法）
class User(Document):  # beanie.Document 子类
    name: str
    ...
await mongo.register_document_models([User])

# 多文档事务（需副本集；事务内操作自动携带事务 session）
async with mongo.transaction() as session:
    await session.insert_one("accounts", {"user_id": 1, "balance": 100})
    await session.update_one("accounts", {"user_id": 1}, {"$inc": {"balance": -50}})
```

**自定义实现接入**：实现 `MongoDatabaseFactoryInterface`（+ 可选能力），`MongoDatabaseRegistry.register("my_mongo", factory)` 注册后
按 `app.mongo.type: my_mongo` 装配，无需改动框架装配代码。

## 5. 注册发现模块（registry）

### 5.1 ServiceRegistryInterface —— 服务注册发现通用接口

- 文件：`src/web_infra/registry/service_registry_interface.py`
- 定位：屏蔽 Nacos/Eureka/Consul 等注册中心差异，用户可自行实现替换（规范 §3 与 §1.3 微服务适配）。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async register(service_name: str, instance: ServiceInstance) -> bool` | 注册服务实例 |
| `async deregister(service_name: str, instance: ServiceInstance) -> bool` | 注销服务实例 |
| `async get_instances(service_name: str) -> list[ServiceInstance]` | 发现服务实例列表（仅健康实例） |
| `async close() -> None` | 释放底层资源 |

- 默认实现：`InMemoryServiceRegistry`（`in_memory.py`，单体/测试场景）；分布式实现：`NacosDiscoveryClient`（`nacos_discovery.py`，官方 nacos-sdk-python v2，gRPC 协议，临时实例由 SDK 自动心跳保活），`NacosRegistration`（`nacos_registration.py`）为注册流程封装工具类。
- 装配：`ServiceDiscoveryRegistry`（`service_discovery_registry.py`）按 `app.registry.type` 按名装配（内置 `memory`/`nacos`，自定义经 `register(name, factory)` 接入，工厂签名 `(settings) -> ServiceRegistryInterface`）；未注册 type 启动期快速失败（`ConfigError`）。

## 6. 负载均衡模块（loadbalance）

### 6.1 LoadBalancerInterface —— 负载均衡器抽象接口

- 文件：`src/web_infra/loadbalance/load_balancer_interface.py`
- 定位：从可用实例列表中选择一个实例，用户可自定义策略（规范 §3 与 §1.3 微服务适配）。
- 类型：`ABC`

| 方法 | 说明 |
| ---- | ---- |
| `choose(instances: list[ServiceInstance]) -> ServiceInstance` | 从实例列表中选择一个实例 |

- 默认实现：`RandomBalancer`、`RoundRobinBalancer`、`WeightedRoundRobinBalancer`（`random_balancer.py` 等）。

## 7. AI 模块（ai）

### 7.1 ModelProviderInterface —— 模型供应商接口（Provider SPI）

- 文件：`src/web_infra/ai/model_provider_interface.py`
- 定位：模型供应商统一抽象，业务代码只依赖抽象接口与统一出入参结构，供应商 SDK 类型不向上泄漏（AI 规范 §2.1/§2.2）。
- 类型：`ABC`

| 成员 | 说明 |
| ---- | ---- |
| `name: str` | 供应商逻辑名（唯一标识，如 openai / anthropic / deepseek） |
| `async chat(request: ChatRequest) -> ChatResponse` | 对话生成（非流式），抽象方法必实现 |
| `stream_chat(request: ChatRequest) -> AsyncIterator[ChatStreamChunk]` | 流式对话生成（默认不支持，供应商以 async generator 覆写，AI 规范 §9） |
| `async embedding(request: EmbeddingRequest) -> EmbeddingResponse` | 向量化（默认不支持，供应商可覆盖实现） |

- 默认实现：`OpenAICompatibleProvider`（`provider/openai_compatible_provider.py`）。
- 注册：`ModelProviderRegistry.register(provider)` 显式注册；或经配置清单 `app.ai.models` 由 `ModelAutoRegistrar` 自动注册。

### 7.2 ModelConfigStoreInterface —— 模型配置来源接口

- 文件：`src/web_infra/ai/model_config_store_interface.py`
- 定位：用户可接入数据库/配置中心等实现（AI 规范 §2/§3/§17.4）。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async load(model_code: str \| None = None) -> ModelConfig \| None` | 加载模型配置，未找到返回 None |
| `async load_all() -> list[ModelConfig]` | 加载全部模型配置（页面化配置自动注册依据，规范 §17.4/§3.2） |
| `async upsert(config: ModelConfig) -> ModelConfig` | 幂等写入（页面化配置落库入口，按 model_code 存在即更新、缺失即插入；非 SPI 必需，数据库实现提供） |

- 默认实现一：`DictModelConfigStore`（`dict_model_config_store.py`）——内存/yml 清单（`app.ai.models`，`app.ai.store.type=yml` 默认装配）。
- 默认实现二：`SqlAlchemyModelConfigStore`（`sqlalchemy_model_config_store.py`）——数据库 `ai_model_config` 表（基线 DDL/DML 见 `db/init/ddl/002-ai-model-config-init-ddl.sql`、`db/init/dml/002-ai-model-config-init-dml.sql`），`app.ai.store.type=db` 装配，启动生命周期自动同步 SPI 注册表。
  - 构造：接收 SQLAlchemy `async_sessionmaker[AsyncSession]` 会话工厂；数据源跟随用户配置的数据库组件（不锁死 MySQL）——`app.db.type=mysql` 复用数据库组件 `session_factory`（同库部署）；多数据源（`DatabaseManager`）取首个数据源；`app.db.type=sqlite` 基于 `SqliteSessionFactory.db_path` 构建独立 SQLAlchemy aiosqlite 异步引擎（sqlite 组件为同步 sqlite3 会话，模型配置表走独立异步连接，`:memory:` 为独立内存库建议使用文件路径）；拿不到异步会话工厂时装配快速失败（`ConfigError`）。
  - 释放：自建引擎（sqlite 场景）经 `SqlAlchemyModelConfigStore.close()` 释放，应用停机生命周期自动调用；mysql 场景复用数据库组件引擎无需释放。
  - 密钥安全（AI 规范 §3.1/AI-7）：`api_key` 列仅存 `env:VAR` 环境变量引用（如 `env:LLM_API_KEY`），真实密钥由应用进程从环境变量/.env 注入，`ModelConfig.resolved_api_key` 运行时解析，禁止明文落盘。

#### 7.2.1 ModelConfigStoreRegistry —— 模型配置来源注册表

- 文件：`src/web_infra/ai/model_config_store_registry.py`
- 定位：模型配置来源 SPI 装配入口（类级注册，全局装配）。yml 配置 `app.ai.store.type` 按名查注册表实例化；内置 `yml` 条目，用户自定义来源（配置中心/Redis 等）经注册即可接入 `create_app`，无需改动框架装配代码；未注册的 `store.type` 启动期快速失败（`ConfigError`，避免拼写错误静默回落）。
- 注册方式：`ModelConfigStoreRegistry.register(name, factory)`，`factory` 为无参工厂，返回 `ModelConfigStoreInterface` 实现；同名覆盖，`unregister` 注销。

| 方法 | 说明 |
| ---- | ---- |
| `register(name, factory)` | 注册 store 工厂（同名覆盖） |
| `unregister(name)` | 注销 store（不存在静默） |
| `get(name) -> factory` | 按名查询工厂（未注册抛 `KeyError`，装配期转 `ConfigError`） |
| `create(name) -> store` | 按名实例化 store |
| `registered_names() -> list[str]` | 已注册 store 名清单 |

### 7.3 ContentGuardInterface —— 内容安全审核接口

- 文件：`src/web_infra/ai/content_guard_interface.py`
- 定位：输入审核（禁止敏感/危险内容进入模型）与输出审核（拦截违规生成内容）（AI 规范 §7.2）。
- 类型：`ABC`

| 方法 | 说明 |
| ---- | ---- |
| `check_input(text: str) -> GuardResult` | 审核输入内容（进入模型前调用） |
| `check_output(text: str) -> GuardResult` | 审核输出内容（返回用户前调用） |

- 默认实现：`RuleBasedContentGuard`（`rule_based_content_guard.py`）。

### 7.4 QuotaStoreInterface —— 配额计数存储接口

- 文件：`src/web_infra/ai/quota/quota_store.py`
- 定位：配额计数存储抽象（AI 规范 §5.3），默认内存实现；多实例需实现 Redis 等共享存储（INCR + TTL 窗口）。
- 类型：`ABC`；辅助结构 `QuotaCounter(calls, tokens, cost)`

| 方法 | 说明 |
| ---- | ---- |
| `async incr(key: str, *, calls: int, tokens: int, cost: float, window_seconds: int) -> QuotaCounter` | 按窗口累加计数（窗口过期自动重置），返回累加后的计数；首次写入时设置 TTL |

- 默认实现：`InMemoryQuotaStore`（`quota/in_memory_quota_store.py`）。

### 7.5 PromptTemplateStoreInterface —— 提示词模板存储接口

- 文件：`src/web_infra/ai/prompt/prompt_template_store_interface.py`
- 定位：提示词模板存储抽象（AI 规范 §6.1），支持内存（默认）与业务自定义实现（如数据库 prompt_templates 表）。
- 类型：`ABC`

| 方法 | 说明 |
| ---- | ---- |
| `async load(key: str, version: str \| None = None) -> PromptTemplate \| None` | 按 key（可指定版本）加载模板；未找到返回 None |
| `async save(template: PromptTemplate) -> None` | 保存/更新模板 |

- 默认实现：`InMemoryPromptTemplateStore`（`prompt/in_memory_prompt_template_store.py`）。

### 7.6 UsageRecordStoreInterface —— 用量记录存储接口

- 文件：`src/web_infra/ai/usage_record_store.py`
- 定位：Token 用量与成本记录持久化抽象（AI 规范 §5.2），默认仅结构化日志输出；业务可对接数据库等实现该接口做计费/审计。
- 类型：`ABC`

| 方法 | 说明 |
| ---- | ---- |
| `async save(record: UsageRecord) -> None` | 持久化一条用量记录 |

- 默认实现：框架内置仅结构化日志输出（无独立存储类）。

### 7.7 VectorStoreInterface —— 向量存储接口

- 文件：`src/web_infra/ai/retrieval/vector_store_interface.py`
- 定位：向量库抽象（AI 规范 §11），提供增删查与按 ID 取回；FAISS / Elasticsearch 等真实向量库可通过该接口接入。
- 类型：`ABC`
- **tenant_id 可选**（2026-08-18 评审调整，租户非系统必备，与 `SearchEngineInterface` 一致）：显式传入时按租户隔离命名空间；
  缺省从请求上下文（`RequestContext`）读取；再无则回落 `no-tenant` 占位——单租户系统无需传租户，所有数据收敛同一命名空间。

| 方法 | 说明 |
| ---- | ---- |
| `add(tenant_id, ids, vectors) -> None` | 批量写入向量（ID 与向量一一对应，仅写入指定租户命名空间） |
| `delete(tenant_id, ids) -> None` | 批量删除指定租户下的向量 |
| `search(tenant_id, query_vector, top_k) -> list[VectorHit]` | 按相似度检索指定租户命名空间内 top_k 个命中（得分越大越相似） |
| `get(tenant_id, ids) -> dict[str, list[float]]` | 按 ID 取回指定租户下的向量（用于邻居扩展等场景），未找到的 ID 不返回 |
| `ids_in_order(tenant_id) -> list[str]` | 按写入顺序返回指定租户下全部向量 ID（供邻居扩展定位相邻块） |

- 默认实现：`InMemoryVectorStore`（`retrieval/in_memory_vector_store.py`，内存字典 + 余弦相似度，单实例/测试场景）。
- 生产实现：`ElasticsearchVectorStore`（`retrieval/elasticsearch_vector_store.py`，dense_vector + kNN，依赖 `es` extra，见 §20.3）。
- 组装：`Retriever` 从请求上下文读取租户传给向量存储（tenant_id 可选），无租户时由实现回落 `no-tenant` 占位。

### 7.8 EmbeddingProviderInterface —— 向量嵌入供应商接口

- 文件：`src/web_infra/ai/retrieval/embedding_provider.py`
- 定位：Embedding 供应商抽象（AI 规范 §11），业务接入 bge-m3 / OpenAI 等模型时实现该接口。
- 类型：`ABC`

| 方法 | 说明 |
| ---- | ---- |
| `embed(text: str) -> list[float]` | 将单段文本转为向量 |
| `embed_batch(texts: list[str]) -> list[list[float]]` | 批量将文本转为向量（顺序与入参一致） |

- 默认实现：`HashEmbeddingProvider`（`retrieval/hash_embedding_provider.py`，规范 S3-1：扩展点必须有默认实现）——基于稳定哈希的定长（默认 256 维）确定性嵌入，不依赖外部模型服务，仅保证同文本向量稳定可比较（本地检索/降级兜底）；生产环境应注入真实模型供应商（bge-m3/OpenAI 等）。

### 7.9 DocumentChunkerInterface —— 文档切片接口

- 文件：`src/web_infra/ai/retrieval/document_chunker.py`
- 定位：文档切片器抽象（AI 规范 §11），按文档类型提供实现。
- 类型：`ABC`

| 方法 | 说明 |
| ---- | ---- |
| `chunk(document: str) -> list[Chunk]` | 将文档切分为有序切片列表（切片携带标题上下文，原子块不拆分） |

- 默认实现：`MarkdownChunker`（`retrieval/markdown_chunker.py`）。

### 7.10 RerankerInterface —— 检索结果重排接口

- 文件：`src/web_infra/ai/retrieval/reranker.py`
- 定位：检索结果重排抽象（AI 规范 §11：Rerank 提升检索精度），可接入 CrossEncoder 等模型实现。
- 类型：`ABC`

| 方法 | 说明 |
| ---- | ---- |
| `rerank(query: str, documents: list[str]) -> list[float]` | 对文档列表按 query 重排打分，返回与 documents 顺序一致的重排分数（越大越相关） |

- 默认实现：`IdentityReranker`（`retrieval/identity_reranker.py`）。

### 7.11 ModelProviderFactory.register_factory —— 供应商构建器注册点

- 文件：`src/web_infra/ai/model_provider_factory.py`
- 定位：自定义协议供应商接入点（AI 规范 §17.4/§2.1）。未注册的协议一律回落 OpenAI 兼容格式（默认协议）；私有化/自定义供应商经 `register_factory` 注册后由配置自动装配。

| 方法 | 说明 |
| ---- | ---- |
| `register_factory(provider_type: str, factory: Callable[[ModelConfig], ModelProviderInterface]) -> None` | 注册自定义供应商构建器（provider_type 与 `ModelConfig.provider` 字段匹配） |

### 7.12 ModelAccessPolicy —— 模型/能力使用权限策略（SPI）

- 文件：`src/web_infra/ai/model_access_policy.py`
- 定位：按 RBAC 校验模型/能力使用权限（AI 规范 §5.5 / 整改 AI-8）。`ModelGateway` 可选注入该策略，chat/stream_chat/embed 三入口调用前强校验，无权限抛 `E2-PERM-000`。
- 类型：`ABC`

| 方法 | 说明 |
| ---- | ---- |
| `check_access(model_name: str, tenant_id: str, user_id: str, scene: str \| None = None) -> bool` | 校验指定模型是否允许当前租户/用户/场景使用（抽象方法，业务 RBAC 实现） |
| `require_access(...) -> None` | 强校验：`check_access` 不允许时抛 `PermException`（E2-PERM-000），网关默认调用此方法 |

- 默认实现：`AllowAllModelAccessPolicy`（恒放行，保持网关默认行为；业务注入 RBAC 策略后生效）。
- 接入：`ModelGateway(..., access_policy=MyAccessPolicy())` 或经网关工厂装配。

## 8. 缓存模块（cache）

### 8.1 CacheBackendInterface —— 缓存后端统一抽象接口

- 文件：`src/web_infra/cache/cache_backend_interface.py`
- 定位：异步缓存后端抽象，屏蔽本地缓存/Redis/配置中心缓存差异，防止技术栈锁定（规范 §8 与 §16.5）。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async get(key: str) -> Any \| None` | 读取缓存，未命中返回 None |
| `async set(key: str, value: Any, ttl: int \| None = None, ttl_jitter_seconds: float \| None = None) -> None` | 写入缓存；`ttl_jitter_seconds` 为 TTL 抖动上限（None 用后端默认配置、0 关闭，规范 §8.3 防雪崩） |
| `async delete(key: str) -> None` | 删除缓存 |
| `async exists(key: str) -> bool` | 判断缓存是否存在 |
| `async set_empty(key: str, ttl: int = 60) -> None` | 写入空值占位（数据不存在标记，规范 §8.2 防穿透；TTL 默认 60，上限 `EMPTY_TTL_LIMIT_SECONDS`=120 自动钳制） |
| `async is_empty(key: str) -> bool` | 判断是否处于空值占位状态（过期自动失效返回 False） |

- 默认实现：`MemoryCacheBackend`（`memory_cache_backend.py`，本地缓存 TTL 自动钳制为分布式 TTL 的 1/3，规范 §8）；分布式实现：`RedisCacheBackend`（`db/redis_cache_backend.py`）。
- 装配：`CacheBackendRegistry`（`cache_backend_registry.py`）按 `app.cache.type` 按名装配（内置 `memory`/`redis`，自定义经 `register(name, factory)` 接入，工厂签名 `(settings) -> CacheBackendInterface`）；未注册 type 启动期快速失败（`ConfigError`）。

## 9. 消息队列模块（mq）

### 9.1 MessagePublisherInterface —— 消息发布者接口

- 文件：`src/web_infra/mq/message_publisher_interface.py`
- 定位：消息发布者抽象（规范 §9）。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async publish(message: Message) -> str` | 发送消息，返回消息 ID；`Message.partition_key` 存在时按业务主键哈希选分区（规范 §9.2 分区内串行） |
| `async send_delay(message: Message, delay_seconds: int) -> str` | 发送延迟消息（规范 §9.5），返回消息 ID；RocketMQ 实现映射官方固定 delay level（1s~2h 共 18 档，禁止 sleep） |

- 默认实现：`InMemoryMessageQueue`（`in_memory_message_queue.py`）；分布式实现：`RocketMqPublisher`（`rocketmq_publisher.py`）。
- 装配：`MessageQueueRegistry`（`message_queue_registry.py`）按 `app.mq.type` 按名装配（内置 `memory`/`rocketmq`，自定义经 `register(name, factory)` 接入，工厂签名 `(settings) -> MessagePublisherInterface`）；未注册 type 启动期快速失败（`ConfigError`）。

### 9.2 MessageConsumerInterface —— 消息消费者接口

- 文件：`src/web_infra/mq/message_consumer_interface.py`
- 定位：消息消费者抽象（规范 §9）。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `subscribe(topic: str, handler: MessageHandler) -> None` | 订阅主题并注册处理器 |
| `async start() -> None` | 启动消费 |
| `async stop() -> None` | 停止消费 |

- 默认实现：`InMemoryMessageQueue`（`in_memory_message_queue.py`）。

### 9.3 MessageIdempotencyStoreInterface —— 消息幂等键存储接口

- 文件：`src/web_infra/mq/message_idempotency_store_interface.py`
- 定位：消息消费幂等键存储抽象（规范 §9.2：bizId + msgId 联合幂等，保留 7 天；Redis SETNX / DB 唯一约束保证跨实例原子性）。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async try_consume(key: str, ttl_seconds: int) -> bool` | 尝试写入消费幂等键：首次写入成功返回 True；已存在（重复消费）返回 False（规范 §9.2） |
| `async release(key: str) -> None` | 回滚占用（业务处理失败时调用，允许重试，规范 §9.6） |

- 默认实现：`InMemoryMessageIdempotencyStore`（`in_memory_message_idempotency_store.py`）；Redis 实现：`RedisMessageIdempotencyStore`（`redis_message_idempotency_store.py`）。

### 9.4 OutboxStoreInterface —— Outbox 存储接口

- 文件：`src/web_infra/mq/outbox/outbox_store_interface.py`
- 定位：Outbox 本地事务表存储抽象（规范 §21.3：定时扫描待发送 -> 投递 -> 更新状态；已发送记录保留 7 天后清理）。MySQL 等实现接入 DDL `db/init/ddl/001-mq-init-ddl.sql`。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async append(record: OutboxRecord) -> OutboxRecord` | 追加一条待发送消息（本地事务提交时调用），返回补齐 msg_id/created_at 的记录 |
| `async next_pending(limit: int = 100) -> list[OutboxRecord]` | 取待发送消息（按创建时间升序，供轮询投递，规范 §21.3） |
| `async mark_sent(msg_id: str) -> None` | 投递成功：状态置为已发送（规范 §21.3） |
| `async mark_failed(msg_id: str, max_retries: int) -> None` | 投递失败：重试次数 +1；超限置为失败超限（规范 §9.6 重试上限告警） |
| `async cleanup_sent(before: datetime) -> int` | 清理已发送超过保留期的记录（以 created_at 判断，规范 §21.3），返回清理条数 |

- 默认实现：`InMemoryOutboxStore`（`outbox/in_memory_outbox_store.py`）。

### 9.5 MessageQueueSelector —— 消息分区选择器（SPI）

- 文件：`src/web_infra/mq/message_queue_selector.py`
- 定位：消息分区选择抽象（规范 §9.2：按业务主键哈希选分区，分区内串行消费）。`RocketMqPublisher` 构造时可注入自定义选择器；内存队列按分区入队（单 worker 天然分区内串行）。
- 类型：`ABC`

| 方法 | 说明 |
| ---- | ---- |
| `select(topic: str, partition_key: str \| None, partition_count: int) -> int` | 选择消息落区索引（[0, partition_count)；partition_key 为空或 partition_count<=0 返回 0） |

- 默认实现：`HashMessageQueueSelector`（zlib.crc32 稳定哈希取模：相同业务分区键恒落同区，不同键尽量均匀分布）。

## 10. 监控模块（monitoring）

### 10.1 MetricGroupProviderInterface —— 自定义指标分组 SPI 接口

- 文件：`src/web_infra/monitoring/metric_group_provider_interface.py`
- 定位：业务侧自行创建 Prometheus 指标并实现本接口，声明「分组名 + 指标名前缀」，注册到 `MetricGroupProviderRegistry` 后，`/metrics` 可视化页面自动将匹配指标归入该分组展示，无需改动框架代码。
- 类型：`ABC`

| 成员 | 说明 |
| ---- | ---- |
| `group_name: ClassVar[str]` | 分组名（可视化页面导航与折叠区块标题） |
| `metric_prefixes: ClassVar[tuple[str, ...]]` | 指标名匹配前缀，命中任一前缀即归入该分组 |
| `series_label_zh(display_name: str, labels: tuple[tuple[str, str], ...]) -> str \| None` | 将指标某个 series 的标签组合翻译为中文说明；返回 None 使用默认 k=v 格式展示 |

- 注册方式：`MetricGroupProviderRegistry.register(provider)`，注册顺序即页面分组顺序；`unregister(group_name)` 可注销。
- 默认实现：`DefaultMetricGroupProvider`（`default_metric_group_provider.py`，规范 S3-2：扩展点默认实现）——按指标名前缀分组（`web_*`→web、`db_*`→db、`mq_*`→mq、`ai_*`→ai、`cache_*`→cache，其余→other），支持构造参数自定义前缀映射；业务实现本接口可覆盖默认分组。

### 10.2 ComponentMetricsCollector —— 组件指标采集器抽象基类

- 文件：`src/web_infra/monitoring/component_metrics_interface.py`
- 定位：框架组件（缓存/存储/消息队列/注册中心等）指标采集器的懒注册基类：指标仅在组件实际被调用（启用）时注册，未启用组件不产生任何指标。
- 类型：抽象基类（类属性 `_registered`/`_lock` + 类方法）

| 成员 | 说明 |
| ---- | ---- |
| `ensure() -> None`（类方法） | 注册组件指标（线程安全，仅首次执行）。子类必须实现，且须覆写独立的 `_registered`/`_lock` 类属性 |

- 内置子类：`CacheMetrics`（`cache_metrics.py`）、`StorageMetrics`（`storage_metrics.py`）、`MqMetrics`（`mq_metrics.py`）、`RegistryMetrics`（`registry_metrics.py`）。

### 10.3 ThreadPoolMetrics —— 线程池指标注册表（SPI 风格）

- 文件：`src/web_infra/monitoring/runtime_metrics.py`
- 定位：业务将线程池注册后由 `record_runtime_metrics` 统一采样，自动在 `/metrics` 展示（工作线程/空闲线程/队列积压）。

| 方法 | 说明 |
| ---- | ---- |
| `register(pool: ThreadPoolExecutor, name: str) -> ThreadPoolExecutor` | 注册线程池（同名覆盖），返回原线程池便于链式调用 |
| `unregister(name: str) -> None` | 注销线程池（线程池关闭时调用，防悬垂指标） |
| `collect() -> None` | 采样全部已注册线程池并写入 Gauge |

## 11. 安全模块（security）

### 11.1 CaptchaStoreInterface —— 验证码存储接口

- 文件：`src/web_infra/security/captcha_store_interface.py`
- 定位：验证码存储抽象，一次性消费语义由 `take()` 保证（取走即删除），支持内存（默认）与 Redis 实现（规范 §25 应用层安全）。
- 类型：`ABC`

| 方法 | 说明 |
| ---- | ---- |
| `async save(captcha_id: str, code: str, ttl_seconds: int) -> None` | 保存验证码（含有效期） |
| `async take(captcha_id: str) -> str \| None` | 取走验证码（一次性消费：成功取走后即删除，未命中/过期返回 None） |

- 默认实现：`InMemoryCaptchaStore`（`in_memory_captcha_store.py`）；多实例实现：`RedisCaptchaStore`（`redis_captcha_store.py`）。

### 11.2 SocialPlatform —— 三方平台适配接口

- 文件：`src/web_infra/security/social/social_platform_interface.py`
- 定位：三方登录平台适配 SPI（规范 §6.8 认证域），业务实现具体平台（微信/GitHub/钉钉等）后注册进 `SocialPlatformRegistry`。
- 类型：`Protocol`（`@runtime_checkable`）

| 成员 | 说明 |
| ---- | ---- |
| `provider: str` | 平台标识（注册表键），如 wechat_open / github / demo |
| `async build_authorize_url(state: str, redirect_uri: str) -> str` | 生成授权跳转 URL（state 由调用方生成用于防 CSRF） |
| `async exchange_token(code: str, redirect_uri: str) -> SocialAccessToken` | 授权码换取平台 token |
| `async fetch_userinfo(token: SocialAccessToken) -> SocialUserInfo` | 拉取三方用户信息（token 内含 access_token/openid/raw，供微信等需 openid 的接口使用） |

- 默认实现：`DemoSocialPlatform`（`demo_social_platform.py`，模拟平台不触网，测试/演示/回落）。

### 11.3 SocialBindingStore —— 三方账号绑定存储接口

- 文件：`src/web_infra/security/social/social_binding_store.py`
- 定位：三方账号 ↔ 本地用户绑定存储 SPI（唯一键 provider + openid，一用户可绑多平台多账号）。
- 类型：`Protocol`（`@runtime_checkable`）；辅助结构 `SocialBinding(provider, openid, user_id, bound_at)`

| 方法 | 说明 |
| ---- | ---- |
| `async find_by_platform(provider: str, openid: str) -> SocialBinding \| None` | 按平台 + openid 查绑定 |
| `async find_all_by_user_id(user_id: str) -> list[SocialBinding]` | 查用户全部三方绑定 |
| `async bind(binding: SocialBinding) -> None` | 绑定（provider+openid 唯一，已存在抛 COMMON_CONFLICT） |
| `async unbind(provider: str, openid: str) -> bool` | 解绑，返回是否实际删除 |

- 默认实现：`InMemorySocialBindingStore`（`in_memory_social_binding_store.py`，单实例）；多实例需业务扩展 Redis/DB 实现。
- 并发（2026-08-16 加固）：内存实现 bind 的"检查-写入"由 RLock 原子化；`SocialLoginService.bind` 对并发竞态（检查与落库间另一请求已先行绑定）捕获 COMMON_CONFLICT 后重查，属主为当前用户则幂等返回，多实例下由 DB 唯一约束兜底。

### 11.4 JwtTokenStore —— JWT Token 状态存储接口

- 文件：`src/web_infra/security/jwt_token_store_interface.py`
- 定位：JWT Token 状态存储 SPI（规范 §6.2 同设备凭证复用、§6.7 凭证撤销）。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async save(user_id, jti, ttl_seconds, client_id, device_id) -> str \| None` | 保存有效凭证；返回被同设备复用替换的旧 jti（无则 None） |
| `async exists(user_id, jti) -> bool` | 查询凭证是否有效（撤销/过期/复用替换后 False） |
| `async revoke(user_id, jti) -> bool` | 撤销凭证（登出） |
| `async current_jti(user_id, client_id, device_id) -> str \| None` | 查询同设备当前有效 jti |

- 默认实现：框架启用 Redis（`app.cache.type=redis`，Application 装配自动注入）时默认 `RedisJwtTokenStore`（分布式，Key 经 CacheKeyBuilder 生成）；未启用 Redis 回落 `InMemoryJwtTokenStore`（单实例）。
- 注入：`JWTUtil.configure(token_store=..., key_provider=...)` 注入自定义实现（**优先级最高**，覆盖框架默认）；`JWTUtil.set_redis(redis)` 显式指定 Redis 客户端；均未注入时按"Redis 默认 → 内存回落"自动选择。
- 并发/内存（2026-08-16 加固）：
  - `JWTUtil` SPI 注入与懒初始化由类级锁保护（双重检查），多线程首次并发调用仅构建一个 store/key_provider，避免状态写入丢失。
  - `InMemoryJwtTokenStore` 惰性清理过期条目（`exists`/`save` 时同步回收 `_states`/`_device_map`/`_user_jtis`），RLock 保护复合读写，防内存无界增长与跨线程状态丢失。
  - 同设备当前 jti 查询：异步调用方推荐 `await JWTUtil.get_current_device_jti_async(...)`（无同步桥接的线程创建与事件循环绑定风险，Redis 状态存储场景必须使用）；同步兼容入口 `JWTUtil.get_current_device_jti(...)` 保留，仅适用于内存实现。

### 11.5 JwtKeyProvider —— JWT 签名密钥/算法接口

- 文件：`src/web_infra/security/jwt_key_provider_interface.py`
- 定位：JWT 签名密钥与算法 SPI（规范 §6.1 单独密钥段防混用、S15-3 密钥轮换），开发者可替换为 RS256/KMS 托管等。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `access_secret() -> str` | access token 签名密钥 |
| `refresh_secret() -> str` | refresh token 单独密钥段（与 access 双向防混用） |
| `algorithm() -> str` | 签名算法（如 HS256/RS256） |

- 默认实现：`EnvJwtKeyProvider`（`env_jwt_key_provider.py`，环境变量密钥 + HS256）。

## 12. 存储模块（storage）

### 12.1 ObjectStorageInterface —— 对象存储统一抽象接口

- 文件：`src/web_infra/storage/object_storage_interface.py`
- 定位：对象存储统一抽象，屏蔽 MinIO/云 OSS/S3 差异（规范 §22）。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async put(bucket: str, key: str, data: bytes, content_type: str \| None = None) -> None` | 上传对象 |
| `async get(bucket: str, key: str, *, owner: str \| None = None, owner_validator: OwnerValidator \| None = None) -> bytes \| None` | 下载对象，不存在返回 None；`owner`/`owner_validator` 为可插拔属主校验钩子（防水平越权下载，规范 §22.4，缺省 None 不校验） |
| `async delete(bucket: str, key: str, *, owner: str \| None = None, owner_validator: OwnerValidator \| None = None) -> None` | 删除对象（owner/owner_validator 语义同 get，规范 §22.4 防越权删除） |
| `async exists(bucket: str, key: str) -> bool` | 判断对象是否存在 |
| `async presign_url(bucket: str, key: str, expires: int \| None = None) -> str` | 生成带过期时间的访问 URL（真实对象存储为签名 URL，规范 §22.3） |

> 类型别名：`OwnerValidator = Callable[[str, str \| None, str \| None], None]`（object_id / owner / current_user，校验失败抛权限异常，如 `PermException` E2-PERM-*）。

- 默认实现：`LocalObjectStorage`（`local_object_storage.py`，presign_url 返回带 `expires`+HMAC `signature` 的受限 URL）；对象存储实现：`MinioStorage`（`minio_storage.py`）。
- 装配：`ObjectStorageRegistry`（`object_storage_registry.py`）按 `app.storage.type` 按名装配（内置 `local`/`minio`，自定义经 `register(name, factory)` 接入，工厂签名 `(settings) -> ObjectStorageInterface`）；未注册 type 启动期快速失败（`ConfigError`）。

### 12.2 PartStorageInterface —— 分片存储接口

- 文件：`src/web_infra/storage/upload/part_storage_interface.py`
- 定位：分片上传的底层分片存储抽象（规范 §22.4）：逐片存取、断点续传列出已传分片、合并与合并后清理。本地磁盘与 MinIO 分段上传为两种实现。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async save_part(upload_id: str, part_number: int, data: bytes) -> None` | 保存单个分片（重试幂等，覆盖同分片重传，规范 §22.4 断点续传） |
| `async list_parts(upload_id: str) -> list[int]` | 列出已存在分片序号（升序） |
| `async read_part(upload_id: str, part_number: int) -> bytes` | 读取单个分片内容（合并校验 MD5 时使用） |
| `async merge(upload_id: str, object_key: str) -> int` | 按分片序号合并为完整对象，返回合并后大小（字节）；合并后清理分片 |
| `async remove_task(upload_id: str) -> None` | 清理任务全部分片与临时记录（合并后/取消时，§22.4） |

- 默认实现：`LocalPartStorage`（`local_part_storage.py`）；对象存储实现：`MinioPartStorage`（`minio_part_storage.py`）。

### 12.3 UploadStoreInterface —— 分片上传任务存储接口

- 文件：`src/web_infra/storage/upload/upload_store_interface.py`
- 定位：分片上传任务记录存储抽象（规范 §22.4）。内存实现默认，多实例可扩展 Redis/MySQL。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async create(task: UploadTask) -> UploadTask` | 创建上传任务（初始化，规范 §22.4） |
| `async get(upload_id: str) -> UploadTask \| None` | 按 upload_id 查询任务（断点续传定位依据） |
| `async mark_part_uploaded(upload_id: str, part_number: int) -> None` | 记录分片上传成功（断点续传查询已传分片） |
| `async list_uploaded_parts(upload_id: str) -> list[int]` | 列出已上传分片序号（客户端断点续传） |
| `async complete(upload_id: str, object_key: str) -> None` | 标记任务合并完成（合并后清理临时任务记录，§22.4） |
| `async cleanup(before: datetime) -> int` | 清理过期未完成/已完成任务记录（配合定时任务，§22.4 临时目录 TTL 清理） |

- 默认实现：`InMemoryUploadStore`（`upload/in_memory_upload_store.py`）。

## 13. 异步任务模块（task）

### 13.1 TaskRecordStoreInterface —— 任务记录存储接口

- 文件：`src/web_infra/task/task_record_store.py`
- 定位：异步任务记录存储抽象（规范 §23.4），默认内存实现，多实例/需持久化时可对接 MySQL 等实现；更新采用乐观锁（version 匹配），避免并发覆盖终态。
- 类型：`ABC`

| 方法 | 说明 |
| ---- | ---- |
| `async save(record: TaskRecord) -> None` | 保存任务记录（新增或全量覆盖） |
| `async load(task_id: str) -> TaskRecord \| None` | 按任务 ID 加载记录；未找到返回 None |
| `async update(record: TaskRecord) -> bool` | 乐观锁更新：仅当存储中版本与 record.version 一致时写入并自增版本；版本不一致返回 False |
| `async list_all() -> list[TaskRecord]` | 列出全部任务记录（供死任务扫描等场景遍历） |

- 默认实现：`InMemoryTaskRecordStore`（`in_memory_task_record_store.py`）。

## 14. Web 模块（web）

### 14.1 IdempotencyStoreInterface —— API 幂等键存储接口

- 文件：`src/web_infra/web/idempotency_store_interface.py`
- 定位：API 幂等键存储抽象（规范 §12.6：幂等键 + 请求摘要 + 处理结果三要素存储，TTL 覆盖重试窗口如 24h；Redis/DB 保证原子性）。
- 类型：`Protocol`（`@runtime_checkable`）；辅助结构 `IdempotencyResult(status_code, content_type, body, request_hash)`

| 方法 | 说明 |
| ---- | ---- |
| `async try_occupy(key: str, ttl_seconds: int) -> bool` | 原子占用幂等键（SETNX 语义）：首次返回 True，重复占用返回 False（规范 §12.6 原子性） |
| `async set_result(key: str, result: IdempotencyResult, ttl_seconds: int) -> None` | 保存首次处理结果 |
| `async get_result(key: str) -> IdempotencyResult \| None` | 读取已缓存的处理结果（未完成或无结果返回 None） |
| `async release(key: str) -> None` | 释放占用（业务处理异常时调用，允许后续请求重试） |

- 默认实现：`InMemoryIdempotencyStore`（`in_memory_idempotency_store.py`）；Redis 实现：`RedisIdempotencyStore`（`redis_idempotency_store.py`）。
- 中间件装配（`app.web.middlewares.idempotency.store_type`）：`memory`（默认，单实例）/ `redis`（跨实例原子，复用已装配 cache 组件 `RedisCacheBackend` 的 Redis 客户端，需 `app.cache.type=redis`）；`store_type=redis` 但 cache 组件非 Redis 时启动期快速失败（`ConfigError`）。

## 15. 支付模块（payment）

> **可选能力（2026-08-17）**：支付不随 `web_infra` 顶层导出，`import web_infra` 不加载支付模块/不注册支付错误码；
> 需要支付的系统显式 `from web_infra.capabilities.payment import ...` 主动引入（如 `from web_infra.capabilities.payment import PaymentGateway`）。

### 15.1 PaymentGateway —— 支付网关统一抽象接口

- 文件：`src/web_infra/capabilities/payment/payment_gateway_interface.py`
- 定位：渠道统一抽象（下单/查单/关单/退款/查退款），业务代码只依赖本接口，金额统一 `Decimal`（元），渠道差异内部屏蔽。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async prepay(request: PaymentPrepayRequest) -> PaymentPrepayResponse` | 下单：按场景返回 prepay_id/调起参数/code_url/h5_url |
| `async query_order(out_trade_no: str) -> PaymentOrder \| None` | 查单；不存在返回 None |
| `async close_order(out_trade_no: str) -> None` | 关闭订单 |
| `async refund(request: PaymentRefundRequest) -> PaymentRefundResponse` | 申请退款（out_refund_no 幂等） |
| `async query_refund(out_refund_no: str) -> PaymentRefundResponse \| None` | 查退款；不存在返回 None |

- 默认实现：`InMemoryPaymentGateway`（单机/测试）；微信渠道：`WeChatPayProvider`（`web_infra.capabilities.payment.provider.wechat`）。
- 注册：`PaymentGatewayRegistry.register(name, gateway)`。
- 微信平台证书：`platform_cert` 模式下可开启 `cert_auto_download`（配置 `app.payment.wechat.cert_auto_download: true`），
  应答验签遇未知证书序列号时自动调用 `GET /v3/certificates` 下载平台证书并缓存至 `platform_cert_dir`（默认关闭，首次可用
  `WeChatPayClient.download_certificates()` 主动预热）。
- 并发/性能（2026-08-16 加固）：证书落盘采用"临时文件 + `os.replace`"原子写，并发验签不会读到半截 PEM；证书/私钥文件读取对
  并发清理与密钥轮换容错（缺失返回 None、mtime 变化自动重读）；商户私钥 PEM 与解析后的 RSA 密钥按内容进程内缓存，高频下单/验签避免重复读盘与重复解析。
- 渠道调用失败兜底（2026-08-16 新增）：`WeChatPayClient` 对网络异常 / 微信 5xx / 429 按指数退避（含抖动）自动重试
  （默认 `retries=2`，`WechatPayConfig.retries` 可调、`0` 关闭）；4xx 业务错误不重试，重试耗尽统一抛 `E3-PAY-000`（渠道可重试错误码）。
  支付接口 `out_trade_no` / `out_refund_no` 天然幂等，重试安全；失败后建议调用 `query_order` 查单确认实际状态再决策。
  下单为资金操作，`request(retryable=False)` 禁止盲目重试（规范 §7.2 红线），失败由业务先查单确认再决策。
- 渠道骨架层（2026-08-16 新增，规范 §3.1/§3.2）：`PaymentChannelTemplate`（ABC）固化资金流程骨架，
  `prepay/refund/close_order/handle_callback/validate_callback` 为 final 入口不可覆写，渠道实现方只填充必选抽象
  `_do_prepay/_do_query_order/_do_close_order/_parse_callback`（漏实现无法实例化）与可选 `_do_refund/_do_query_refund`
  （默认抛 `E4-PAY-008`）。骨架统一编排：下单幂等（§4.2）→ 渠道调用 → 三态收敛 → 流水落库（§5.2）；
  关单前查单确认防已支付被关闭（§5.5）；回调金额/attach/状态机强校验（§4.3/§4.5）。
  注入 `flow_store`（支付流水）与 `order_store`（本地支付订单）后兜底全量生效；未注入降级为纯渠道调用（兼容 SPI 直用）。
  默认实现 `InMemoryPaymentGateway` 已骨架化（可注入存储，测试/单机即获全套兜底）；`WeChatPayProvider` 为微信骨架实现。
- 契约测试与回调模拟器（2026-08-16 新增，规范 §3.3/§10.3）：`web_infra.capabilities.payment.testing` 提供
  `PaymentChannelContract`（9 个资金场景契约用例，任意骨架实现 run_all() 校验）与 `PaymentCallbackSimulator`
  （支付/退款/金额不符/attach 不符回调报文构造，可注入签名钩子）。

### 15.2 PaymentCallbackVerifier —— 支付回调验签解密接口

- 文件：`src/web_infra/capabilities/payment/payment_callback_verifier_interface.py`
- 定位：解析渠道回调 headers+body 为统一回调结构；验签/解密失败返回 None（回调入口回 401，渠道自动重试）。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async parse(headers: Mapping[str, str], body: str) -> PaymentCallback \| None` | 验签+解密+解析；失败返回 None |

- 默认实现：`InMemoryPaymentCallbackVerifier`（单机/测试）；微信渠道：`WeChatCallbackVerifier`（平台证书/微信支付公钥两种模式，AES-256-GCM 解密）。
- 平台证书自动下载：构造时注入 `WeChatPayClient` 且开启 `cert_auto_download` 后，回调验签遇未知序列号自动下载平台证书并缓存。

### 15.3 PaymentCallbackHandler —— 支付回调业务处理器接口

- 文件：`src/web_infra/capabilities/payment/payment_callback_handler_interface.py`
- 定位：业务实现处理支付成功/退款结果回调；回调幂等由业务保证。
- 类型：`ABC`（业务必选，无默认实现）

| 方法 | 说明 |
| ---- | ---- |
| `async handle(callback: PaymentCallback) -> None` | 处理一条支付/退款回调 |

- 装配：`PaymentCallbackDispatcher.register(handler)`；`dispatch` 顺序调用全部注册处理器，无处理器时静默兜底（日志告警）。

### 15.4 对账机制（§6，2026-08-17 新增）

- 文件：`src/web_infra/capabilities/payment/reconciliation/`
- 定位：对账是回调通道之外的第二道资金一致性防线（规范 §6）：渠道账单 vs 本地流水逐笔对齐。
- 组件：
  - `BillRecord`：渠道账单统一交易明细（订单号 + 事件类型 + 金额 + 状态，对齐 §2.2）。
  - `ReconciliationService.reconcile(bill_records, local_flows, ...)`：对齐 → 差异分类（§6.3 五类 + 风险等级）→ 自动处理（§6.4：CHANNEL_ONLY 查单确认后补记、LOCAL_ONLY 查单确认未支付后冲正；金额/状态不一致强制人工 P0 告警，未确认不处理资金）。
  - `ReconciliationAuditStore`（SPI + InMemory）：差异清单/处理动作只增不改（§6.6）。
  - `run_reconciliation(...)`：T+1 对账任务函数（唯一标识 `pay:job:reconcile:{channel}:{biz_date}` + 分布式防重，§6.5），由业务注册到 `TaskScheduler`。
  - `BillFileManager`：账单文件完整性校验（文件头/长度/校验和）+ 按账期组织 + 保留期 ≥ 90 天归档（§6.7）。
- 生产化依赖：本地流水查询（MySQL 本地事务表）、账单下载/解析（渠道 API）、审计/账单对象存储由业务接入。

### 15.5 冲正（§7.5，2026-08-17 新增）

- 文件：`src/web_infra/capabilities/payment/payment_reversal.py`
- 定位：对"不应发生或状态未知"的本地记账做反向调整；只适用支付后阶段，必须基于渠道权威状态。
- `reversal_flow(flow_store, original_flow, ...)`：新增反向冲正流水（不可删原流水，原流水自动标记 REVERSED）+ 幂等（原流水号 + REVERSAL 唯一）+ 禁止冲正冲正流水 + 冲正事件钩子（下游业务补偿，失败不阻塞冲正流水）。

### 15.6 风控限额（§9，2026-08-17 新增）

- 文件：`src/web_infra/capabilities/payment/risk/`
- 定位：资金流出/流入受限额与频次约束（工程可配置约束）。
- 组件：`PaymentLimitConfig`（渠道 → `LimitRule` 配置化）、`LimitCounterStore`（Decimal 精确累计 + 原子，SPI + InMemory；生产 Redis 跨实例）、`PaymentRiskGuard.check_prepay(...)`（单笔/日/月限额 E4-PAY-005、频次 E4-PAY-006、可疑拆分 E4-PAY-007）。

### 15.7 支付审计（§8.3，2026-08-17 新增）

- 文件：`src/web_infra/capabilities/payment/payment_audit_store.py`
- 定位：支付全链路审计（下单/回调/入账/退款/冲正/对账差异），只增不改，成功与失败同样留痕，携带 TraceId/订单号/渠道交易号；渠道原始报文（raw）仅落审计不落业务日志（§8.6）。
- 接入：`PaymentAuditStoreInterface`（SPI + InMemory）；渠道骨架 final 入口（prepay/refund/close_order/handle_callback）构造时注入 `audit_store` 即自动埋点（未注入默认关闭）。

### 15.8 支付权限点（§8.4，2026-08-17 新增）

- 文件：`src/web_infra/capabilities/payment/payment_permission.py`
- 定位：`PaymentPermission` 常量（`AUTH_PERM_` 前缀）：下单/查单/关单/退款/冲正/对账/账单管理分离；退款/冲正/人工补记属高风险操作（独立权限点 + 审批流 + 全量审计），由业务接入框架 RBAC/审批组件按权限点拦截。

## 16. 日志模块（logging）

### 16.1 LogSinkInterface —— 日志输出通道接口

- 文件：`src/web_infra/logging/log_sink_interface.py`
- 定位：日志输出通道 SPI。日志的**存储位置/传输方式**（控制台、本地文件、远端日志平台、消息队列等）可配置且可扩展：
  内置 `console`（控制台）与 `file`（文件，按天轮转）两条通道，经 `app.logging.output`（both/console/file，
  默认 both：控制台 + 文件同时输出）与 `app.logging.file` / `app.logging.retention_days` 配置；
  自定义通道经 `LogSinkRegistry.register` 注册后，在 `app.logging.sinks.<name>` 声明即启用。
- 方法契约：

| 方法 | 说明 |
| ---- | ---- |
| `create_handler(options: dict \| None = None) -> logging.Handler` | 构造日志输出 Handler（标准库 `logging.Handler` 或子类）；框架统一挂载格式器（text/json，规范 §17.2）与 ContextFilter / SensitiveDataFilter（§17.1/§17.3），保证输出格式与脱敏一致 |

- 内置实现：
  - `ConsoleLogSink`：`logging.StreamHandler`（控制台）；
  - `FileLogSink`：`TimedRotatingFileHandler`（按天轮转 + 保留天数，目录自动创建，`encoding="utf-8"`）。
- 注册表：`LogSinkRegistry`（类级注册，同名覆盖内置/已注册通道），`register(name, factory)` 注册工厂
  `(options: dict | None) -> LogSinkInterface`；未注册的通道名在 `configure_logging` / `create_app` 装配期快速失败。
- 配置示例：

```yaml
app:
  logging:
    level: INFO
    format: text        # text | json
    output: both        # both（默认，控制台+文件）/ console（仅控制台）/ file（仅文件）
    file: logs/app.log  # 文件路径（output 含 file 时生效，目录自动创建）
    retention_days: 30  # 文件保留天数（按天轮转，规范 §17.2 要求 ≥30 天）
    sinks:              # 自定义日志通道（LogSinkInterface SPI）：name -> 通道配置
      elk:
        url: http://log-collector:8200
```

- 接入示例（自定义通道）：

```python
# my_log_sink.py（create_app 前导入即注册，幂等）
import logging
from web_infra.infra.logging import LogSinkRegistry


class HttpLogSink:  # LogSinkInterface 为 Protocol，结构子类型，方法签名匹配即可
    def create_handler(self, options=None):
        # 自定义 Handler：将日志投递到远端日志平台（options 为 app.logging.sinks.<name> 配置）
        return MyHttpLogHandler(**(options or {}))


LogSinkRegistry.register("elk", lambda options: HttpLogSink())
```

```yaml
app:
  logging:
    output: console      # 仅保留控制台
    sinks:
      elk:               # 自定义通道与内置通道并存
        url: http://log-collector:8200
```

- 输出通道配置：`configure_logging(output=..., log_file=..., sinks=...)`（`output` 仅控制台/仅文件/两者，
  None 按 `log_file` 推导向后兼容）；`Application` 装配读取 `app.logging.output/file/retention_days/sinks`，
  配置非法（未注册通道、`output=file` 缺路径）抛 `ConfigError` 快速失败。

## 17. 扩展接入指引

### 17.1 接入步骤

1. 确定目标 SPI 接口（见第 2 节总览表），实现其全部抽象方法。
   - `Protocol` 类型：结构子类型，类无需继承接口，方法签名匹配即可；`ABC` 类型：继承接口并实现 `@abstractmethod`。
2. 通过注册表显式注册（或配置声明装配）。
3. 多实例/跨进程场景，默认内存实现需替换为共享存储实现（Redis/MySQL 等）。

### 17.2 三方平台接入步骤（参照 `DemoSocialPlatform`）

1. 实现 `SocialPlatform`（`build_authorize_url` / `exchange_token` / `fetch_userinfo`，Protocol 结构子类型，无需继承）。
2. `SocialPlatformRegistry.register(platform)` 显式注册。
3. 构造 `SocialLoginService(registry, binding_store)`，在业务 Controller 中编排跳转/回调登录/绑定/解绑。
4. 登录成功由 `SocialLoginService.login` 复用 `JWTUtil` 签发框架自有 JWT，后续鉴权走 `AuthMiddleware`。
5. 多实例部署时替换绑定存储：实现 `SocialBindingStore` 的 Redis/DB 版并注入。

### 17.3 自定义模型供应商示例（参照 `OpenAICompatibleProvider`）

```python
# my_provider.py
from web_infra.capabilities.ai.chat_request import ChatRequest
from web_infra.capabilities.ai.chat_response import ChatResponse
from web_infra.capabilities.ai.model_provider_interface import ModelProviderInterface
from web_infra.capabilities.ai.model_provider_registry import ModelProviderRegistry


class MyProvider(ModelProviderInterface):
    name = "my-llm"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        # 对接自有模型服务，返回统一 ChatResponse
        ...


ModelProviderRegistry.register(MyProvider())
```

### 17.4 自定义对象存储实现示例（参照 `MinioStorage`）

```python
# my_storage.py
from web_infra.capabilities.storage.object_storage_interface import ObjectStorageInterface


class MyObjectStorage(ObjectStorageInterface):
    async def put(self, bucket: str, key: str, data: bytes, content_type: str | None = None) -> None:
        ...

    async def get(self, bucket: str, key: str) -> bytes | None:
        ...

    async def delete(self, bucket: str, key: str) -> None:
        ...

    async def exists(self, bucket: str, key: str) -> bool:
        ...

    async def presign_url(self, bucket: str, key: str, expires: int | None = None) -> str:
        ...
```

### 17.5 自定义指标分组示例（参照 `metric_group_provider_interface.py`）

```python
# my_metrics_group.py
from web_infra.infra.monitoring.metric_group_provider_interface import MetricGroupProviderInterface
from web_infra.infra.monitoring.metric_group_provider_registry import MetricGroupProviderRegistry


class OrderMetricsGroup(MetricGroupProviderInterface):
    group_name = "订单业务指标"
    metric_prefixes = ("biz_order_",)

    def series_label_zh(self, display_name: str, labels: tuple[tuple[str, str], ...]) -> str | None:
        labels_map = dict(labels)
        if labels_map.get("status") == "success":
            return "成功"
        if labels_map.get("status") == "failed":
            return "失败"
        return None


MetricGroupProviderRegistry.register(OrderMetricsGroup())
```

### 17.6 常见替换对照

| 场景 | 默认实现 | 替换实现 |
| ---- | ---- | ---- |
| 单实例 -> 多实例（验证码/幂等/消息幂等） | 内存实现 | Redis 实现（已内置） |
| 单实例 -> 多实例（任务/上传/Outbox/配额） | 内存实现 | MySQL/Redis 自定义实现 |
| 单体 -> 微服务 | `InMemoryServiceRegistry` | `NacosDiscoveryClient`/`NacosRegistration`（已内置） |
| 本地存储 -> 对象存储 | `LocalObjectStorage` | `MinioStorage`（已内置） |
| 本地 MQ -> 分布式 MQ | `InMemoryMessageQueue` | `RocketMqPublisher`（已内置） |
| 接入新模型供应商 | `OpenAICompatibleProvider` | 自定义 `ModelProviderInterface` 实现 |

## 18. 能力注册表（capability）

> **能力依赖模型（2026-08-17）**：支付的前置是鉴权，鉴权的前置是认证，认证的前置是用户系统（否则无意义）。
> 框架声明能力契约（SPI）与依赖包含规则，启用能力时按包含关系自动启用前置（启用支付默认启用鉴权→认证→用户，以此类推）；
> 具体业务实现（如用户系统 user-service）交由业务层提供。

### 18.1 能力契约与内置依赖图

- 文件：`src/web_infra/capability/`（`Capability` / `CapabilityRegistry` / `CapabilityError` / `CapabilityResolution` / `CapabilityValidation`）
- `Capability`（契约）：能力名 / 说明 / 随能力启用的框架模块（modules）/ 前置能力（requires，按包含关系自动启用）/ 业务契约（contract）。
- 注册：`CapabilityRegistry.register(Capability(...))`（同名覆盖；前置允许后置注册，未知前置在解析/校验时拦截；不能依赖自身）。
- 内置依赖图（导入 `web_infra.core.capability` 自动注册）：

| 能力 | 框架模块 | 前置 | 说明 |
| ---- | ---- | ---- | ---- |
| `user` | 无（业务实现） | - | 用户系统：契约能力，业务层实现（如脚手架 user-service）；框架侧接入点 RequestContext / SocialBindingStore / OAuth2 |
| `authn` | `web_infra.capabilities.security` | `user` | 认证：确认『你是谁』——JWT 签发/校验、Token 存储、三方登录、OAuth2 登录（前置用户系统） |
| `authz` | `web_infra.capabilities.security` | `authn` | 鉴权：确认『你能做什么』——权限守卫/RBAC（PermissionGuard，前置认证） |
| `pay` | `web_infra.capabilities.payment` | `authz` | 支付：渠道 SPI + 回调验签/分发 + 骨架兜底 + 对账/冲正/风控（前置鉴权，传递依赖认证/用户） |
| `ai` | `web_infra.capabilities.ai` | - | AI 模型网关：供应商/模型路由/配额/检索/内容安全 |
| `mq` | `web_infra.capabilities.mq` | - | 消息队列：发布/幂等消费/事务发件箱 |
| `storage` | `web_infra.capabilities.storage` | - | 对象存储与分片上传 |
| `registry` | `web_infra.capabilities.registry` | - | 服务注册发现与负载均衡 |
| `config` | `web_infra.infra.config` | - | 配置（本地源 + Nacos 配置中心） |
| `db` | `web_infra.capabilities.db` | - | 数据访问（ORM 会话/读写分离/多租户过滤） |
| `cache` | `web_infra.capabilities.cache` | - | 缓存（内存/Redis） |
| `search` | `web_infra.capabilities.search` | - | 搜索引擎：全文检索 SPI（默认 memory，生产 ES）+ 向量 kNN（es extra，延迟导入） |

### 18.2 依赖解析（resolve）与装配校验（validate）

- `CapabilityRegistry.resolve(name)`：按包含关系展开传递前置，返回 `CapabilityResolution`（拓扑序能力链 chain、需导入框架模块 modules）；
  未注册能力 / 依赖循环抛 `CapabilityError`。
- `CapabilityRegistry.validate(enabled)`：装配校验，返回 `CapabilityValidation`（ok / unknown 未知能力 / circular 循环链路 /
  closure 完整闭包 / chain 拓扑序）。**缺前置不视为失败**——按包含关系自动补足（如启用 pay 闭包自动含 user/authn/authz）。

```python
from web_infra import CapabilityRegistry

resolution = CapabilityRegistry.resolve("pay")
assert [c.name for c in resolution.chain] == ["user", "authn", "authz", "pay"]  # 启用支付自动带上前置（认证/鉴权均依赖用户）
assert resolution.modules == ("web_infra.capabilities.security", "web_infra.capabilities.payment")

validation = CapabilityRegistry.validate(["pay"])
assert validation.ok and validation.closure == frozenset({"user", "authn", "authz", "pay"})
```

### 18.3 启用能力（enable / app.capabilities.enabled）

- 运行时显式启用：`CapabilityRegistry.enable("pay")` —— 解析（校验）后按拓扑序自动导入前置与目标能力的框架模块（幂等）。
- 配置驱动装配（推荐）：`application.yml` 声明 `app.capabilities.enabled`，`create_app` 装配时自动校验（未知能力/循环抛
  `ConfigError`）并按拓扑序启用：

```yaml
app:
  capabilities:
    enabled: [pay]   # 自动启用 鉴权(authz)→认证(authn)→用户系统(user)（业务实现由业务层提供）
```

> **默认状态**：`app.capabilities.enabled` 默认空（`[]`）——业务可选能力链（user / authn / authz / pay）默认全部关闭，按需启用；
> 认证/鉴权与支付一样依赖用户系统（JWT/权限守卫等安全工具代码随核心可导入，能力启用需用户前置）。
> 框架内置模块能力（config / db / cache / mq / storage / registry / ai）的框架代码随核心安装即可用
> （内存/本地实现开箱即用，外部实现需对应 extras + 配置），在 `enabled` 中声明仅用于显式装配校验与依赖展开。

### 18.4 业务扩展自定义能力

业务层（使用框架的项目开发者）按同一机制登记业务能力并声明依赖（以此类推）：

```python
from web_infra import Capability, CapabilityRegistry

CapabilityRegistry.register(Capability(
    name="order",            # 业务能力名
    description="订单域（业务实现）",
    requires=("pay",),       # 依赖支付 → 自动带出 auth / user
    contract="订单业务由业务层实现",
))
CapabilityRegistry.enable("order")
```

## 19. 统一扩展注册器（extension）

### 19.1 定位与边界

- 文件：`src/web_infra/extension/`（`ExtensionPoint` / `ExtensionRegistry` / `ExtensionError` / `ExtensionResolution` / `ExtensionValidation`）
- **定位（2026-08-18）**：为「各种数据源 / 其他插件」提供统一扩展入口。与第 4~16 章领域注册表（`DatabaseRegistry` 等）的边界是
  **「上层编排层」**：领域注册表按名管资源工厂（装配期实例化，如 `app.db.type=mysql`）；扩展注册器管插件协议对象
  （`build/startup/shutdown` 生命周期 + 依赖顺序）。两者互补不冲突，插件可自行选择：
  - 纯资源替换（如新增 PostgreSQL 数据源）→ 走领域注册表（§4.2，已支持混合多源并存）；
  - 有生命周期/横切性质的插件（第三方 SDK 初始化与释放、启动订阅、定时资源）→ 走扩展注册器。
- **冲突避免规则**（与框架生态设计一致，不引入平行体系）：
  - 同名默认拒绝（`overwrite=True` 才覆盖），避免误覆盖内置/已注册条目；
  - 命名带命名空间（如 `datasource.postgres`、`sdk.loki`），不与内置短名冲突；
  - 契约只进不退：`build/startup/shutdown` 均为可选钩子，新能力只增不改；
  - 延迟启用：插件经 `app.extensions.enabled` 配置驱动启用，未启用不实例化。

### 19.2 扩展点契约（ExtensionPoint）

| 字段 | 类型 | 说明 |
| ---- | ---- | ---- |
| `name` | str | 扩展点名（注册表键，与 `app.extensions.enabled` 匹配） |
| `description` | str | 扩展点说明 |
| `requires` | tuple[str, ...] | 前置扩展点名（按拓扑序先启用；未知/循环装配期快速失败） |
| `build` | Callable \| None | 装配期构建器，签名 `(options, ctx) -> 实例`；`options` 为 `app.extensions.<name>` 配置段，`ctx` 含 `{"settings", "components"}` |
| `startup` | Callable \| None | 启动钩子，入参 build 产物（同步/异步皆可） |
| `shutdown` | Callable \| None | 停机钩子，入参 build 产物（同步/异步皆可） |

### 19.3 注册（同名默认拒绝）

- `ExtensionRegistry.register(extension, overwrite=False)`：同名默认拒绝（抛 `ExtensionError`），显式 `overwrite=True` 才覆盖。
- `get(name)`（未注册返回 None）/ `names()` / `unregister(name)`（静默）。
- 校验：扩展点名不能为空、不能依赖自身。

### 19.4 依赖解析（resolve）与装配校验（validate）

- `ExtensionRegistry.resolve(name)`：按依赖包含规则展开传递前置，返回 `ExtensionResolution`（拓扑序扩展点链 chain，前置在前）；
  未注册 / 依赖循环抛 `ExtensionError`。
- `ExtensionRegistry.validate(enabled)`：返回 `ExtensionValidation`（ok / unknown / circular / closure / chain）。
  **缺前置不视为失败**——按包含关系自动补足。

```python
from web_infra import ExtensionRegistry

resolution = ExtensionRegistry.resolve("child")   # requires=("parent",)
assert [e.name for e in resolution.chain] == ["parent", "child"]

validation = ExtensionRegistry.validate(["child"])
assert validation.ok and validation.closure == frozenset({"parent", "child"})
```

### 19.5 配置驱动启用（app.extensions.enabled）

`create_app` 装配时校验（未知扩展点/依赖循环抛 `ConfigError`）并按拓扑序构建实例，实例挂 `app.state.extensions`：

```yaml
app:
  extensions:
    enabled: [my_plugin]      # 声明即启用（默认空 []，业务按需声明）
    my_plugin:                # 扩展点配置段，透传给 build 的 options
      endpoint: https://example.com
```

### 19.6 生命周期编排（startup 拓扑序 / 停机逆序）

- 装配顺序：`logging → capabilities → components → extensions → web → tenant → health`。
  `build` 在组件装配之后执行——插件可复用已装配组件（`ctx["components"]`，如 Redis 客户端）。
- 启动：`startup` 按拓扑序执行（前置先启动）；停机：`shutdown` 按逆拓扑序执行（后启先停），
  且**先于框架组件 close**（插件可能依赖框架组件，先用完再关底层）。
- 钩子同步/异步皆可（返回 awaitable 自动 await）。

### 19.7 接入示例（业务插件）

```python
# my_plugin.py（create_app 前导入即注册；或项目入口显式 import）
from web_infra import ExtensionPoint, ExtensionRegistry

def build_client(options, ctx):
    # options: app.extensions.my_plugin 配置段；ctx: {"settings", "components"}
    return SdkClient(endpoint=options.get("endpoint"))

async def close_client(client):
    await client.close()

ExtensionRegistry.register(ExtensionPoint(
    name="my_plugin",
    description="第三方 SDK 插件（启动初始化/停机释放）",
    build=build_client,
    startup=lambda client: client.connect(),   # 同步/异步皆可
    shutdown=close_client,
))
```

```yaml
# application.yml
app:
  extensions:
    enabled: [my_plugin]
    my_plugin:
      endpoint: https://example.com
```

装配后业务通过 `app.state.extensions["my_plugin"]` 访问插件实例。

> **完整可运行示例**：数据源插件（实现 `DatabaseFactoryInterface` + `ExtensionPoint` 生命周期钩子，含两种接入路径）
> 见 [examples/demo_datasource_extension.py](../examples/demo_datasource_extension.py)，配套测试
> [tests/test_example_demo_datasource.py](../tests/test_example_demo_datasource.py)。

## 20. 搜索引擎模块（search）

> 搜索引擎能力（2026-08-18 落地，搜索引擎接入计划 v0.2.0）：全文检索 SPI 三件套 + ES 生产实现
> （elasticsearch-dsl ORM），向量检索复用 `VectorStoreInterface` 接入 dense_vector + kNN。
> 与缓存/对象存储同属**顶层导出能力**（默认实现无外部依赖），es extra 仅 ES 生产实现需要。

### 20.1 SearchEngineInterface —— 全文搜索引擎接口

- 文件：`src/web_infra/search/search_engine_interface.py`
- 定位：全文搜索引擎统一抽象（索引生命周期 / 写入 / 删除 / 关键词检索），业务代码只依赖本接口，屏蔽 ES / 内存 / 自研差异。
- 类型：`Protocol`（`@runtime_checkable`），全部方法 **async**。
- **tenant_id 可选**（2026-08-18 评审调整，租户非系统必备）：显式传入时按租户隔离命名空间（多租户规范 §2：禁止跨租户命中）；
  缺省从请求上下文（`RequestContext`）读取；再无则回落 `no-tenant` 占位（`TenantGuard.current_tenant`）——单租户系统无需传租户，
  所有数据收敛同一命名空间，隔离退化为全局共享。

| 方法 | 说明 |
| ---- | ---- |
| `async create_index(tenant_id, index_name, *, mappings=None, settings=None)` | 创建索引（幂等：已存在静默）；`mappings` 支持业务自定义分析器/分词器（如 IK 中文分词），`settings` 覆盖分片/副本 |
| `async delete_index(tenant_id, index_name)` | 删除索引（幂等：不存在静默） |
| `async index_document(tenant_id, index_name, doc_id, document, *, refresh=False)` | 写入/覆盖单条文档（doc_id 幂等，全量替换） |
| `async bulk_index(tenant_id, index_name, documents, *, refresh=False)` | 批量写入（元素必须含 `id` 键作为文档标识，缺 id 跳过并告警，不中断整批） |
| `async delete_document(tenant_id, index_name, doc_id, *, refresh=False)` | 按文档 ID 删除（幂等：不存在静默） |
| `async search(tenant_id, query: SearchQuery) -> list[SearchHit]` | 关键词检索，按相关性降序返回命中（得分/原文/可选高亮） |

检索参数 `SearchQuery`（`search_query.py`）：`keyword`（必填）、`index_name`（默认 `default`）、
`offset/size`（分页，对应 ES from/size）、`highlight`（高亮开关）。命中结果 `SearchHit`（`search_hit.py`）：
`id / score / source（原文）/ highlight（字段 → 片段列表）`。

### 20.2 默认实现与生产实现

| 实现 | 文件 | 说明 |
| ---- | ---- | ---- |
| `InMemorySearchEngine` | `in_memory_search_engine.py` | **默认实现**：内存倒排 + 简单分词（中文单字/英文单词）+ 简化 BM25 打分 + 高亮（`<em>` 包裹）；按（租户+索引）命名空间隔离，容量上限按命名空间淘汰最旧（防内存无限增长）；单实例/测试场景，多实例需替换 ES 实现 |
| `ElasticsearchSearchEngine` | `elasticsearch_search_engine.py` | **生产实现**：基于官方 `elasticsearch-dsl`（异步 AsyncSearch/AsyncIndex，检索 DSL 构建），真实索引名 `{index_prefix}_{tenant_id}_{index_name}`；依赖 `es` extra（`elasticsearch-dsl>=8.0`，自动携带 elasticsearch-py），**延迟导入**——未安装 es extra 时导入模块不报错，构造实例才加载并提示安装 |

- 注册装配：`SearchEngineRegistry`（`search_engine_registry.py`）按 `app.search.type` 实例化，
  内置 `memory` / `elasticsearch` 条目；业务自研实现 `register(name, factory)` 后按 type 接入，
  未注册的 type 装配期快速失败（ConfigError），与 `CacheBackendRegistry` / `ObjectStorageRegistry` 同构。
- 租户隔离：真实索引名前缀隔离（如 `web_t1_products`）；`tenant_id` 可选（缺省读请求上下文/回落 `no-tenant`），
  显式传入的 `tenant_id` / `index_name` 禁止含下划线（防拼接歧义）。

### 20.3 向量检索接入（ElasticsearchVectorStore）

- 文件：`src/web_infra/ai/retrieval/elasticsearch_vector_store.py`
- 定位：`VectorStoreInterface` 的 ES 生产实现（搜索引擎接入计划 §3.3）——dense_vector 字段 + ES 8 原生 kNN 查询，
  与 `InMemoryVectorStore` 同一组装方式（注入 `Retriever` / `EmbeddingProviderInterface` 即用，**不改动 retriever.py**）。
- 索引名：`{index_prefix}_{tenant_id}_vector`；写入/检索前自动幂等建索引（`auto_create_index` 可关闭）；
  `dims` 与嵌入模型对齐（默认 768）；`search` 走 `extra(knn=...)`（`num_candidates` 建议 ≥ 10*top_k）。
- 能力说明：ES 不保证写入顺序，`ids_in_order` 按 `_id` 升序返回（邻居扩展定位用；业务可用时间序雪花 ID 编码保证顺序）。

### 20.4 错误码与配置

- 错误码（`search_error_code.py`，模块导入即登记 `ErrorCodeRegistry`，规范 §4）：

| 错误码 | 语义 | HTTP | 可重试 |
| ---- | ---- | ---- | ---- |
| `E3-SRCH-000` | 搜索引擎调用失败（网络/集群不可用等） | 502 | 是 |
| `E3-SRCH-001` | 索引操作失败 | 502 | 是 |
| `E4-SRCH-001` | 搜索引擎未配置/未注册 | 422 | 否 |
| `E4-SRCH-002` | 检索参数非法 | 422 | 否 |
| `E4-SRCH-003` | 索引不存在 | 404 | 否 |

- 配置（`application.default.yml` `app.search` 段 + `SearchConfig` 模型）：`enabled`（默认 false）、
  `type`（`memory` / `elasticsearch` / `custom`）、`index_prefix`（默认 `web`）、`elasticsearch.hosts/username/password/verify_certs/connect_timeout/read_timeout`
  （敏感项经 `APP_SEARCH_ELASTICSEARCH_*` 环境变量注入）。
- 能力登记：`capability` 注册表内置 `search` 能力（无前置，`app.capabilities.enabled: ["search"]` 可声明启用，自动导入 `web_infra.capabilities.search`）。

### 20.5 数据同步 SPI（search 模块，2026-08-22 落地）

> 搜索引擎数据同步方案（CDC 默认 / 双写备选 / 自定义 SPI）：`web_infra.capabilities.search.sync` 提供
> 「业务数据库 → ES」同步——**cdc**（MySQL binlog 旁路，默认）/ **dual_write**（事务内写 outbox）/
> **空闲对账**（reconcile/rebuild 兜底）/ 自定义。位置：`src/web_infra/capabilities/search/sync/`。

**三件套 SPI**：

| SPI | 文件 | 方法 | 默认实现 |
| ---- | ---- | ---- | ---- |
| `CdcSourceInterface` | `cdc_source_interface.py` | `subscribe(handler)` / `start()` / `stop()` | `MysqlBinlogCdcSource`（`mysql-replication`，[cdc] extra 延迟导入） |
| `CdcSyncTargetInterface` | `cdc_sync_target_interface.py` | `upsert(event)` / `delete(event)` / `start()` / `stop()` | `EsCdcSyncTarget`（包装 `SearchEngineInterface`） |
| `CdcOffsetStoreInterface` | `cdc_offset_store_interface.py` | `save(key, position)` / `load(key)` | `RedisOffsetStore`（默认）/ `FileOffsetStore` / `MysqlOffsetStore` |

- 统一事件模型 `CdcChangeEvent`（`cdc_change_event.py`）：`source/database/table/op/primary_key/before/after/position/ts`，
  `op` 枚举 `CdcOp`（insert/update/delete），`document_id` 由主键按列序拼接（稳定幂等）。
- 编排管道 `CdcSyncPipeline`（`cdc_sync_pipeline.py`）：订阅源事件 → 表白名单过滤 → 攒批（bulk_size/flush_interval）→
  目标写入（exponential backoff 重试）→ 成功后推进全局流位点（At-least-once，目标幂等兜底）；失败超限暂停消费。
- 装配注册表 `CdcSyncRegistry`（`cdc_sync_registry.py`）：`register_source/register_target/register_offset_store`，
  内置 `redis`/`file` 位点条目，业务自定义实现 `register_*` 后按 `app.search.sync.source/target/offset_store` 接入，
  未注册抛 KeyError（装配期转 ConfigError）。
- 双写：`SearchSyncOutboxWriter`（本事务内写 outbox 记录）+ `SearchSyncOutboxConsumer`（复用 `IdempotentConsumer` 幂等消费，写目标）。
- 空闲对账：`FullReconcileService`（`full_reconcile_service.py`）——`reconcile`（库 → ES 补齐）/ `rebuild`（重建 + alias 切换），
  注入行读取器解耦；schedule 定时触发，空闲窗口外跳过。
- 埋点：`SyncMetrics`（`search_sync_*`：事件/成功/失败/滞后/位点/对账差异），懒注册模式（随调用注册）。

**错误码**（`search_sync_error_code.py`，模块导入即登记注册表）：

| 错误码 | 语义 | HTTP | 可重试 |
| ---- | ---- | ---- | ---- |
| `E3-SRCH-010` | CDC 数据源读取失败（内部重连） | 502 | 是 |
| `E3-SRCH-011` | 同步目标写入失败 | 502 | 是 |
| `E4-SRCH-012` | 同步配置非法 | 422 | 否 |
| `E4-SRCH-013` | 位点无效或丢失（需对账/重建） | 422 | 否 |

**配置**（`application.default.yml` `app.search.sync` 段 + `CdcSyncConfig` 模型，默认关闭）：
`enabled/type(cdc|dual_write|custom)/source(mysql)/target(es)/offset_store(redis|file|mysql)`、
`cdc.mysql.host/port/username/password/database/server_id/tables/bulk_size/flush_interval_seconds/heartbeat_interval_seconds`、
`retry.max_attempts/backoff_base_seconds/max_backoff_seconds`、`delete_strategy(soft|hard)`、
`dual_write.topic/outbox.event_type`、`reconcile.enabled/mode/cron/window/batch_size/tables`、`mapping`（表 → 索引映射）。

**部署前置**：MySQL `binlog_format=ROW`、`binlog_row_image=FULL`、8.0.14+ `binlog_row_metadata=FULL`；
复制账号需 `REPLICATION SLAVE, REPLICATION CLIENT`；多实例 `server_id` 唯一 + Redis 分布式锁选主。

## 21. 维护指南

| 场景 | 操作位置 |
| ---- | ---- |
| 新增 SPI 接口 | 在对应模块新建 `<职责>_interface.py`（单一职责），同步更新第 2 节总览表 |
| 新增默认实现 | 提供默认实现类并在总览表登记；同步补充单元测试 |
| 修改接口方法 | 同步修改全部实现类与本文档对应方法表 |
| 涉及数据库存储实现 | 同步更新 `db/init/ddl/001-mq-init-ddl.sql` 及对应 DML |
| 新增支付渠道 | 在 `src/web_infra/capabilities/payment/provider/` 继承 `PaymentChannelTemplate`（§3.1 骨架）填充 `_do_*`/`_parse_callback`、声明 `capabilities` 并注册 `PaymentGatewayRegistry`；同步补充契约测试（§15.1/§15.4） |
| 新增搜索引擎实现 | 实现 `SearchEngineInterface`（§20.1）或 `VectorStoreInterface`，注册 `SearchEngineRegistry`；同步补充单元测试与 §2 总览表 |
| 新增同步数据源/目标 | 实现 `CdcSourceInterface` / `CdcSyncTargetInterface`（§20.5），注册 `CdcSyncRegistry`；同步补充单元测试 |
| 新增同步位点存储 | 实现 `CdcOffsetStoreInterface`（§20.5），注册 `CdcSyncRegistry.register_offset_store`；同步补充单元测试与位点表 DDL |
