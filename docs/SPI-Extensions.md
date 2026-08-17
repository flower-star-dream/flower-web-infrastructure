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
- [16. 扩展接入指引](#16-扩展接入指引)
  - [16.1 接入步骤](#161-接入步骤)
  - [16.2 三方平台接入步骤（参照 `DemoSocialPlatform`）](#162-三方平台接入步骤参照-demosocialplatform)
  - [16.3 自定义模型供应商示例（参照 `OpenAICompatibleProvider`）](#163-自定义模型供应商示例参照-openaicompatibleprovider)
  - [16.4 自定义对象存储实现示例（参照 `MinioStorage`）](#164-自定义对象存储实现示例参照-miniostorage)
  - [16.5 自定义指标分组示例（参照 `metric_group_provider_interface.py`）](#165-自定义指标分组示例参照-metricgroupproviderinterfacepy)
  - [16.6 常见替换对照](#166-常见替换对照)
- [17. 维护指南](#17-维护指南)

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
| db | `DatabaseFactoryInterface` | Protocol | `SqliteSessionFactory` | MySQL/PG 工厂 |
| db | `DatabaseRouterInterface` | ABC | `TenantDatabaseRouter` | 自定义路由策略 |
| registry | `ServiceRegistryInterface` | Protocol | `InMemoryServiceRegistry` | Nacos/Eureka/Consul |
| loadbalance | `LoadBalancerInterface` | ABC | `RandomBalancer` / `RoundRobinBalancer` / `WeightedRoundRobinBalancer` | 自定义策略 |
| ai | `ModelProviderInterface` | ABC | `OpenAICompatibleProvider` | Anthropic/DeepSeek 等 |
| ai | `ModelConfigStoreInterface` | Protocol | `DictModelConfigStore` | 数据库/配置中心 |
| ai | `ContentGuardInterface` | ABC | `RuleBasedContentGuard` | 第三方审核服务 |
| ai | `QuotaStoreInterface` | ABC | `InMemoryQuotaStore` | Redis（INCR + TTL 窗口） |
| ai | `PromptTemplateStoreInterface` | ABC | `InMemoryPromptTemplateStore` | 数据库 prompt_templates 表 |
| ai | `UsageRecordStoreInterface` | ABC | 结构化日志输出 | 数据库（计费/审计） |
| ai | `VectorStoreInterface` | ABC | `InMemoryVectorStore` | FAISS/Milvus 等 |
| ai | `EmbeddingProviderInterface` | ABC | `HashEmbeddingProvider`（稳定哈希本地嵌入） | bge-m3/OpenAI 等 |
| ai | `DocumentChunkerInterface` | ABC | `MarkdownChunker` | 按文档类型扩展 |
| ai | `RerankerInterface` | ABC | `IdentityReranker` | CrossEncoder 等 |
| ai | `ModelProviderFactory.register_factory` | 注册表 | OpenAI 兼容回落 | 自定义协议工厂 |
| ai | `ModelAccessPolicy` | ABC | `AllowAllModelAccessPolicy` | RBAC 权限策略 |
| cache | `CacheBackendInterface` | Protocol | `MemoryCacheBackend` | Redis |
| mq | `MessagePublisherInterface` | Protocol | `InMemoryMessageQueue` | RocketMQ/Kafka |
| mq | `MessageConsumerInterface` | Protocol | `InMemoryMessageQueue` | RocketMQ/Kafka |
| mq | `MessageIdempotencyStoreInterface` | Protocol | `InMemoryMessageIdempotencyStore` | Redis SETNX / DB 唯一约束 |
| mq | `MessageQueueSelector` | ABC | `HashMessageQueueSelector` | 自定义分区策略 |
| mq | `OutboxStoreInterface` | Protocol | `InMemoryOutboxStore` | MySQL（DDL 见 db/init/ddl/001-mq-init-ddl.sql） |
| monitoring | `MetricGroupProviderInterface` | ABC | `DefaultMetricGroupProvider` | - |
| monitoring | `ComponentMetricsCollector` | ABC | 内置组件各自子类 | 自定义组件指标 |
| monitoring | `ThreadPoolMetrics` | 注册表 | 内置 | - |
| security | `CaptchaStoreInterface` | ABC | `InMemoryCaptchaStore` | Redis |
| storage | `ObjectStorageInterface` | Protocol | `LocalObjectStorage` | MinIO/云 OSS/S3 |
| storage | `PartStorageInterface` | Protocol | `LocalPartStorage` | MinIO 分段上传 |
| storage | `UploadStoreInterface` | Protocol | `InMemoryUploadStore` | Redis/MySQL |
| task | `TaskRecordStoreInterface` | ABC | `InMemoryTaskRecordStore` | MySQL（乐观锁） |
| web | `IdempotencyStoreInterface` | Protocol | `InMemoryIdempotencyStore` | Redis/DB |
| security | `SocialPlatform` | Protocol | `DemoSocialPlatform` | 微信/GitHub/钉钉等 |
| security | `SocialBindingStore` | Protocol | `InMemorySocialBindingStore` | Redis/MySQL |
| security | `JwtTokenStore` | Protocol | `InMemoryJwtTokenStore` / `RedisJwtTokenStore` | 共享存储 |
| security | `JwtKeyProvider` | Protocol | `EnvJwtKeyProvider` | RS256/KMS 托管 |
| payment | `PaymentGateway` | Protocol | `InMemoryPaymentGateway` | 微信/支付宝等渠道 |
| payment | `PaymentCallbackVerifier` | Protocol | `InMemoryPaymentCallbackVerifier` | 微信回调验签（平台证书/公钥） |
| payment | `PaymentCallbackHandler` | ABC | 无（业务必选） | 支付/退款回调业务处理 |

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

- 默认实现：`DictModelConfigStore`（`dict_model_config_store.py`）。

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
- 定位：向量库抽象（AI 规范 §11），提供增删查与按 ID 取回；FAISS 等真实向量库可通过该接口接入。
- 类型：`ABC`

| 方法 | 说明 |
| ---- | ---- |
| `add(ids: list[str], vectors: list[list[float]]) -> None` | 批量写入向量（ID 与向量一一对应） |
| `delete(ids: list[str]) -> None` | 批量删除向量 |
| `search(query_vector: list[float], top_k: int) -> list[VectorHit]` | 按相似度检索 top_k 个命中（得分越大越相似） |
| `get(ids: list[str]) -> dict[str, list[float]]` | 按 ID 取回向量（用于邻居扩展等场景），未找到的 ID 不返回 |
| `ids_in_order() -> list[str]` | 按写入顺序返回全部向量 ID（供邻居扩展定位相邻块） |

- 默认实现：`InMemoryVectorStore`（`retrieval/in_memory_vector_store.py`）。

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

## 15. 支付模块（payment）

### 15.1 PaymentGateway —— 支付网关统一抽象接口

- 文件：`src/web_infra/payment/payment_gateway_interface.py`
- 定位：渠道统一抽象（下单/查单/关单/退款/查退款），业务代码只依赖本接口，金额统一 `Decimal`（元），渠道差异内部屏蔽。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async prepay(request: PaymentPrepayRequest) -> PaymentPrepayResponse` | 下单：按场景返回 prepay_id/调起参数/code_url/h5_url |
| `async query_order(out_trade_no: str) -> PaymentOrder \| None` | 查单；不存在返回 None |
| `async close_order(out_trade_no: str) -> None` | 关闭订单 |
| `async refund(request: PaymentRefundRequest) -> PaymentRefundResponse` | 申请退款（out_refund_no 幂等） |
| `async query_refund(out_refund_no: str) -> PaymentRefundResponse \| None` | 查退款；不存在返回 None |

- 默认实现：`InMemoryPaymentGateway`（单机/测试）；微信渠道：`WeChatPayProvider`（`web_infra.payment.provider.wechat`）。
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
- 契约测试与回调模拟器（2026-08-16 新增，规范 §3.3/§10.3）：`web_infra.payment.testing` 提供
  `PaymentChannelContract`（9 个资金场景契约用例，任意骨架实现 run_all() 校验）与 `PaymentCallbackSimulator`
  （支付/退款/金额不符/attach 不符回调报文构造，可注入签名钩子）。

### 15.2 PaymentCallbackVerifier —— 支付回调验签解密接口

- 文件：`src/web_infra/payment/payment_callback_verifier_interface.py`
- 定位：解析渠道回调 headers+body 为统一回调结构；验签/解密失败返回 None（回调入口回 401，渠道自动重试）。
- 类型：`Protocol`（`@runtime_checkable`）

| 方法 | 说明 |
| ---- | ---- |
| `async parse(headers: Mapping[str, str], body: str) -> PaymentCallback \| None` | 验签+解密+解析；失败返回 None |

- 默认实现：`InMemoryPaymentCallbackVerifier`（单机/测试）；微信渠道：`WeChatCallbackVerifier`（平台证书/微信支付公钥两种模式，AES-256-GCM 解密）。
- 平台证书自动下载：构造时注入 `WeChatPayClient` 且开启 `cert_auto_download` 后，回调验签遇未知序列号自动下载平台证书并缓存。

### 15.3 PaymentCallbackHandler —— 支付回调业务处理器接口

- 文件：`src/web_infra/payment/payment_callback_handler_interface.py`
- 定位：业务实现处理支付成功/退款结果回调；回调幂等由业务保证。
- 类型：`ABC`（业务必选，无默认实现）

| 方法 | 说明 |
| ---- | ---- |
| `async handle(callback: PaymentCallback) -> None` | 处理一条支付/退款回调 |

- 装配：`PaymentCallbackDispatcher.register(handler)`；`dispatch` 顺序调用全部注册处理器，无处理器时静默兜底（日志告警）。

### 15.4 对账机制（§6，2026-08-17 新增）

- 文件：`src/web_infra/payment/reconciliation/`
- 定位：对账是回调通道之外的第二道资金一致性防线（规范 §6）：渠道账单 vs 本地流水逐笔对齐。
- 组件：
  - `BillRecord`：渠道账单统一交易明细（订单号 + 事件类型 + 金额 + 状态，对齐 §2.2）。
  - `ReconciliationService.reconcile(bill_records, local_flows, ...)`：对齐 → 差异分类（§6.3 五类 + 风险等级）→ 自动处理（§6.4：CHANNEL_ONLY 查单确认后补记、LOCAL_ONLY 查单确认未支付后冲正；金额/状态不一致强制人工 P0 告警，未确认不处理资金）。
  - `ReconciliationAuditStore`（SPI + InMemory）：差异清单/处理动作只增不改（§6.6）。
  - `run_reconciliation(...)`：T+1 对账任务函数（唯一标识 `pay:job:reconcile:{channel}:{biz_date}` + 分布式防重，§6.5），由业务注册到 `TaskScheduler`。
  - `BillFileManager`：账单文件完整性校验（文件头/长度/校验和）+ 按账期组织 + 保留期 ≥ 90 天归档（§6.7）。
- 生产化依赖：本地流水查询（MySQL 本地事务表）、账单下载/解析（渠道 API）、审计/账单对象存储由业务接入。

### 15.5 冲正（§7.5，2026-08-17 新增）

- 文件：`src/web_infra/payment/payment_reversal.py`
- 定位：对"不应发生或状态未知"的本地记账做反向调整；只适用支付后阶段，必须基于渠道权威状态。
- `reversal_flow(flow_store, original_flow, ...)`：新增反向冲正流水（不可删原流水，原流水自动标记 REVERSED）+ 幂等（原流水号 + REVERSAL 唯一）+ 禁止冲正冲正流水 + 冲正事件钩子（下游业务补偿，失败不阻塞冲正流水）。

### 15.6 风控限额（§9，2026-08-17 新增）

- 文件：`src/web_infra/payment/risk/`
- 定位：资金流出/流入受限额与频次约束（工程可配置约束）。
- 组件：`PaymentLimitConfig`（渠道 → `LimitRule` 配置化）、`LimitCounterStore`（Decimal 精确累计 + 原子，SPI + InMemory；生产 Redis 跨实例）、`PaymentRiskGuard.check_prepay(...)`（单笔/日/月限额 E4-PAY-005、频次 E4-PAY-006、可疑拆分 E4-PAY-007）。

### 15.7 支付审计（§8.3，2026-08-17 新增）

- 文件：`src/web_infra/payment/payment_audit_store.py`
- 定位：支付全链路审计（下单/回调/入账/退款/冲正/对账差异），只增不改，成功与失败同样留痕，携带 TraceId/订单号/渠道交易号；渠道原始报文（raw）仅落审计不落业务日志（§8.6）。
- 接入：`PaymentAuditStoreInterface`（SPI + InMemory）；渠道骨架 final 入口（prepay/refund/close_order/handle_callback）构造时注入 `audit_store` 即自动埋点（未注入默认关闭）。

### 15.8 支付权限点（§8.4，2026-08-17 新增）

- 文件：`src/web_infra/payment/payment_permission.py`
- 定位：`PaymentPermission` 常量（`AUTH_PERM_` 前缀）：下单/查单/关单/退款/冲正/对账/账单管理分离；退款/冲正/人工补记属高风险操作（独立权限点 + 审批流 + 全量审计），由业务接入框架 RBAC/审批组件按权限点拦截。

## 16. 扩展接入指引

### 16.1 接入步骤

1. 确定目标 SPI 接口（见第 2 节总览表），实现其全部抽象方法。
   - `Protocol` 类型：结构子类型，类无需继承接口，方法签名匹配即可；`ABC` 类型：继承接口并实现 `@abstractmethod`。
2. 通过注册表显式注册（或配置声明装配）。
3. 多实例/跨进程场景，默认内存实现需替换为共享存储实现（Redis/MySQL 等）。

### 16.2 三方平台接入步骤（参照 `DemoSocialPlatform`）

1. 实现 `SocialPlatform`（`build_authorize_url` / `exchange_token` / `fetch_userinfo`，Protocol 结构子类型，无需继承）。
2. `SocialPlatformRegistry.register(platform)` 显式注册。
3. 构造 `SocialLoginService(registry, binding_store)`，在业务 Controller 中编排跳转/回调登录/绑定/解绑。
4. 登录成功由 `SocialLoginService.login` 复用 `JWTUtil` 签发框架自有 JWT，后续鉴权走 `AuthMiddleware`。
5. 多实例部署时替换绑定存储：实现 `SocialBindingStore` 的 Redis/DB 版并注入。

### 16.3 自定义模型供应商示例（参照 `OpenAICompatibleProvider`）

```python
# my_provider.py
from web_infra.ai.chat_request import ChatRequest
from web_infra.ai.chat_response import ChatResponse
from web_infra.ai.model_provider_interface import ModelProviderInterface
from web_infra.ai.model_provider_registry import ModelProviderRegistry


class MyProvider(ModelProviderInterface):
    name = "my-llm"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        # 对接自有模型服务，返回统一 ChatResponse
        ...


ModelProviderRegistry.register(MyProvider())
```

### 16.4 自定义对象存储实现示例（参照 `MinioStorage`）

```python
# my_storage.py
from web_infra.storage.object_storage_interface import ObjectStorageInterface


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

### 16.5 自定义指标分组示例（参照 `metric_group_provider_interface.py`）

```python
# my_metrics_group.py
from web_infra.monitoring.metric_group_provider_interface import MetricGroupProviderInterface
from web_infra.monitoring.metric_group_provider_registry import MetricGroupProviderRegistry


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

### 16.6 常见替换对照

| 场景 | 默认实现 | 替换实现 |
| ---- | ---- | ---- |
| 单实例 -> 多实例（验证码/幂等/消息幂等） | 内存实现 | Redis 实现（已内置） |
| 单实例 -> 多实例（任务/上传/Outbox/配额） | 内存实现 | MySQL/Redis 自定义实现 |
| 单体 -> 微服务 | `InMemoryServiceRegistry` | `NacosDiscoveryClient`/`NacosRegistration`（已内置） |
| 本地存储 -> 对象存储 | `LocalObjectStorage` | `MinioStorage`（已内置） |
| 本地 MQ -> 分布式 MQ | `InMemoryMessageQueue` | `RocketMqPublisher`（已内置） |
| 接入新模型供应商 | `OpenAICompatibleProvider` | 自定义 `ModelProviderInterface` 实现 |

## 17. 维护指南

| 场景 | 操作位置 |
| ---- | ---- |
| 新增 SPI 接口 | 在对应模块新建 `<职责>_interface.py`（单一职责），同步更新第 2 节总览表 |
| 新增默认实现 | 提供默认实现类并在总览表登记；同步补充单元测试 |
| 修改接口方法 | 同步修改全部实现类与本文档对应方法表 |
| 涉及数据库存储实现 | 同步更新 `db/init/ddl/001-mq-init-ddl.sql` 及对应 DML |
| 新增支付渠道 | 在 `src/web_infra/payment/provider/` 继承 `PaymentChannelTemplate`（§3.1 骨架）填充 `_do_*`/`_parse_callback`、声明 `capabilities` 并注册 `PaymentGatewayRegistry`；同步补充契约测试（§15.1/§15.4） |
