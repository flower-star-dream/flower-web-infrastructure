# 常见问题 FAQ

> 一句话定位：开发者集成框架时的高频疑问与排查思路汇编——每个问题按「问题 → 原因 → 解决」组织，附代码/配置片段与能力文档链接。内容提炼自 [使用说明](../使用说明.md)、[README](../README.md) 与开发者指南 01~22 篇。

## 目录

- [1. 安装与导入](#1-安装与导入)
- [2. 配置](#2-配置)
- [3. 装配与生命周期](#3-装配与生命周期)
- [4. 数据库与缓存](#4-数据库与缓存)
- [5. MQ / Outbox](#5-mq--outbox)
- [6. 认证与权限](#6-认证与权限)
- [7. AI](#7-ai)
- [8. 支付](#8-支付)
- [9. 部署与监控](#9-部署与监控)

---

## 1. 安装与导入

### Q1. 最小安装和 extras 怎么选？

**问题**：`pip install flower-web-infrastructure` 后想用 MySQL / Redis / MinIO / RocketMQ / Nacos / PDF 等能力报错或不可用。

**原因**：核心安装仅含 Web / 配置 / 日志 / 错误码 / 安全工具类 / 监控 / 内存缓存与内存本地组件（内存 MQ、本地存储、内存注册表、SQLite 会话）；MySQL/Redis/Mongo 等 SDK 属**可选 extras**，框架代码中延迟导入，不随核心安装。

**解决**：按能力安装对应 extras（详见 [使用说明.md §1](../使用说明.md#1-安装)）：

```bash
pip install "flower-web-infrastructure[mysql,redis,mongo]"   # 数据访问
pip install "flower-web-infrastructure[storage,rocketmq,nacos]"  # MinIO / RocketMQ / Nacos
pip install "flower-web-infrastructure[pdf]"                  # Playwright PDF 渲染
pip install "flower-web-infrastructure[all]"                  # 全量（开发环境）
# 按架构形态：pip install "flower-web-infrastructure[min-monolith]" / "[min-microservice]"
```

### Q2. 使用 MySQL/Redis/RocketMQ 报 ModuleNotFoundError？

**问题**：代码运行到 `from web_infra.capabilities.db import ...` 或配置 `app.cache.type: redis` 时抛 `ModuleNotFoundError: No module named 'sqlalchemy' / 'redis' / ...`。

**原因**：对应 SDK 是可选依赖，核心安装未携带（延迟导入设计，最小安装零负担）。

**解决**：安装对应 extra 后重试（见 Q1），无需修改业务代码；确认虚拟环境激活正确（`pip show sqlalchemy` 可查）。

### Q3. `import web_infra` 失败 / ModuleNotFoundError？

**问题**：`import web_infra` 直接报错。

**原因**：通常是没有安装框架或虚拟环境未激活。

**解决**：

```bash
pip show flower-web-infrastructure   # 确认已安装
python -c "import web_infra; print(web_infra.__file__)"   # 确认导入路径与虚拟环境一致
```

> 注意：`import web_infra` 与 `from web_infra import *` 均兼容最小安装（不触发可选依赖加载）；已安装 mysql/redis/mongo extras 时 `from web_infra import *` 才自动导出全部能力（含 `Base` / `MySQLConfig` 等），最小安装下这些组件需先装 extras 再显式导入（[使用说明.md §1.1](../使用说明.md#11-最小安装核心默认依赖)）。

### Q4. 升级 v1.0.0 后子包导入报错？

**问题**：升级后 `from web_infra.payment import ...` / `from web_infra.db import ...` 等旧路径导入失败。

**原因**：v1.0.0 包重组为三层结构，**子包路径已迁移**：能力层迁至 `web_infra.capabilities.*`，技术底座迁至 `web_infra.infra.*`。

**解决**：按迁移对照更新导入路径（[使用说明.md 顶部说明](../使用说明.md)）：

```python
# web_infra.payment          → web_infra.capabilities.payment
# web_infra.db               → web_infra.capabilities.db
# web_infra.result           → web_infra.infra.result
# web_infra.application      → web_infra.core.application
# web_infra.config（本地）    → web_infra.infra.config
# web_infra.config（Nacos）   → web_infra.capabilities.config
```

顶层导出不变：`from web_infra import Result, create_app` 照常使用。

## 2. 配置

### Q5. 配置优先级？为什么改的配置不生效？

**问题**：改了 `application.yml` 但运行时仍是旧值。

**原因**：配置存在覆盖层级，更高优先级的来源会覆盖 yml。

**解决**：优先级为 **代码 dict > 环境变量 > 项目根 `.env` > 项目 `application.yml` > 框架默认 `application.default.yml`**（[配置参考 §0](./03-配置参考.md)）。排查顺序：

1. 确认项目根目录存在 `application.yml`（否则走框架默认值）；
2. 确认没有同名 `APP_*` 环境变量 / `.env` 覆盖；
3. 确认没有在 `create_app({"app.xxx": ...})` 传入更高优先级 dict。

### Q6. .env 什么时候加载？模块级读环境变量拿到旧值？

**问题**：`.env` 里配置了 `SNOWFLAKE_WORKER_ID`，但模块级 `os.getenv` 读不到。

**原因**：`.env` 由 `web_infra` 包**导入时**加载（早于 `create_app`）。若业务代码在**导入 web_infra 之前**执行模块级读取，自然拿不到值。

**解决**：把环境变量读取放到运行时（函数内/懒加载）。框架自身已遵循此约定——例如 `SnowflakeUtil` 在**首次生成 ID 时**才读取 `SNOWFLAKE_WORKER_ID`（见 [22-工具类与常量规范.md §3](./22-工具类与常量规范.md#3-雪花-idsnowflakeutil)）。`.env` 已被 `.gitignore` 默认忽略，复制 `.env.example` 填写即可；已存在的进程/容器环境变量优先、不被 `.env` 覆盖（[使用说明.md §3](../使用说明.md#3-配置说明)）。

### Q7. 环境变量映射规则？

**问题**：不知道某个配置项对应的环境变量名。

**解决**：规则为**点号转大写 + 下划线**：`app.db.mysql.host` → `APP_DB_MYSQL_HOST`（[配置参考 §0](./03-配置参考.md)）。例如：

```bash
APP_ENV=prod
APP_DB_MYSQL_HOST=10.0.0.5
APP_CACHE_TYPE=redis
APP_MQ_TYPE=rocketmq
```

YAML 中也可用 `${ENV:default}` 占位符引用：`username: ${APP_DB_MYSQL_USERNAME:root}`（敏感项默认值兜底、避免明文随 yml 提交）。

### Q8. 敏感配置如何加密（enc:）？

**问题**：`JWT_SECRET_KEY` 等密钥不希望明文出现在 `.env`。

**解决**：支持 `enc:` 前缀加密值，经环境变量 `CONFIG_ENCRYPT_KEY`（Fernet 密钥）自动解密（`ConfigCipher`）：

```bash
JWT_SECRET_KEY=enc:gAAAAAB...   # 由 CONFIG_ENCRYPT_KEY 解密后使用
```

详见 [配置参考 §17](./03-配置参考.md#17-其他环境变量非-app-前缀)。

### Q9. JWT_SECRET_KEY 缺失报错？

**问题**：启动或签发 token 时抛 `RuntimeError`（签名密钥缺失）。

**原因**：`EnvJwtKeyProvider` 要求环境变量 `JWT_SECRET_KEY` **必填**（HS256），禁止落盘/写代码。

**解决**：在 `.env` 或容器环境注入（生产用密钥管理服务注入，支持 `enc:` 加密值）：

```bash
JWT_SECRET_KEY=<强随机密钥>   # 建议 ≥32 字节；轮换见 12-认证与安全 §2.2
```

### Q10. Nacos 注册 IP 必须显式注入？

**问题**：生产容器部署后，注册中心上服务 IP 是容器内网地址/错误地址，其他服务调不通。

**原因**：Nacos 注册 IP 按探测优先级取（`register_ip` > `NACOS_REGISTER_IP` > `POD_IP`（K8s）> `HOST_IP` > 默认网关 > UDP 探测 > 回环），容器场景自动探测结果不可靠，**生产容器必须显式注入**（[配置参考 §13](./03-配置参考.md#13-服务注册发现appregistry)）。

**解决**：

```yaml
app:
  registry:
    type: nacos
    nacos:
      register_ip: ${APP_REGISTRY_NACOS_REGISTER_IP:}   # 显式注入对外可访问 IP
```

## 3. 装配与生命周期

### Q11. create_app 之后组件怎么访问？

**问题**：装配完成后不知道如何拿到缓存/数据库/MQ 实例。

**解决**：已装配组件统一挂载 `app.state`，按名访问（[使用说明.md §3](../使用说明.md#3-配置说明)）：

```python
from web_infra import create_app

app = create_app()
cache = app.state.cache        # app.cache.type 装配的后端（memory/redis）
db = app.state.db              # DatabaseManager
mongo = app.state.mongo        # 启用 app.mongo 时存在
storage = app.state.storage
mq = app.state.mq
registry = app.state.registry
ai = app.state.ai              # 启用 app.ai 时存在
```

### Q12. 中间件顺序：为什么 trace_id 必须最后声明？

**问题**：自行调整 `app.web.middlewares` 顺序后 TraceId 丢失/鉴权身份被覆盖。

**原因**：Starlette 中间件**后声明者在外层先执行**。`trace_id` 必须最后声明（最先执行，先生成/透传 TraceId），统一鉴权 `auth` 次之（随后以 token payload 注入身份，不被外层覆盖），幂等 `idempotency` 最内层最后执行（此时身份已就绪）（[配置参考 §3.1](./03-配置参考.md#31-中间件appwebmiddlewares)）。

**解决**：保持默认声明顺序（`trace_id` 在最后）：

```yaml
app:
  web:
    middlewares:
      idempotency: { enabled: true, store_type: redis }
      auth: { enabled: true, whitelist: ["/health", "/metrics", "/docs"] }
      trace_id: {}     # 必须最后声明（最先执行）
```

### Q13. 配置了未注册的组件 type 报 ConfigError？

**问题**：`app.cache.type: xxx` / `app.db.type: pg` / `app.mq.type: kafka` 启动即抛 `ConfigError`。

**原因**：组件按注册表装配，**未注册的 type 启动期快速失败**（防运行时才发现配置错误）。内置注册表条目：cache（memory/redis）、db（mysql/sqlite）、mq（memory/rocketmq）、storage（local/minio）、registry（memory/nacos）、mongo（beanie）、search（memory/elasticsearch）。

**解决**：使用内置 type；接入新实现（如 PostgreSQL）需实现 SPI 并注册进对应注册表（`DatabaseRegistry.register(...)`），再按 type 装配（[06-数据库.md](./06-数据库.md)）。

### Q14. 能力链怎么启用？支付/认证为什么没生效？

**问题**：配置了支付但调用报错/能力未装配。

**原因**：业务可选能力链（user/authn/authz/pay）默认全部关闭；且启用支付按依赖包含规则自动带出 鉴权→认证→用户系统。

**解决**：`app.capabilities.enabled` 声明（未知能力/循环依赖装配期抛 ConfigError）（[使用说明.md §4.2](../使用说明.md#42-能力依赖与装配)）：

```yaml
app:
  capabilities:
    enabled: [pay]    # 自动启用 authz → authn → user（业务实现由业务层提供）
```

## 4. 数据库与缓存

### Q15. db.session() 会话生命周期？

**问题**：需要手动 commit / rollback / close 吗？长事务怎么处理？

**解决**：`db.session()`（文本 SQL）与 `db.orm_session()`（SQLAlchemy AsyncSession）生命周期（提交/回滚/关闭）**由框架自动管理**（[06-数据库.md §3](./06-数据库.md#3-会话生命周期session--orm_session)）：

```python
async with db.session() as session:      # 成功自动提交、异常自动回滚、退出自动关闭
    rows = await session.query_all("SELECT * FROM t")

async with db.orm_session() as session:
    session.add(Order(...))
```

> 注意：长事务审计（>5s 记 warning 并递增 `db_long_transaction_total`，仅告警不阻断）；长耗时外部调用（如 LLM）期间想归还连接用 `connection_released(session)` 上下文管理器。

### Q16. 分页到 10000 条就报错？

**问题**：`PageQuery(page_no=501, page_size=20)` 抛 `ValueError`。

**原因**：深分页拒绝（S10-1）：`offset + page_size` 超过 `PARAM_COMMON_MAX_OFFSET`（10000）直接拒绝，防 `LIMIT offset` 深分页拖垮数据库；每页大小上限 `PARAM_COMMON_MAX_PAGE_SIZE`（500）。

**解决**：改用**游标分页** `CursorPageQuery`（首页 `cursor=None`，后续页携带上一页最后一条排序字段值）（[06-数据库.md §7](./06-数据库.md#7-分页pagequery--cursorpagequery)）：

```python
from web_infra.capabilities.db import CursorPageQuery

q = CursorPageQuery(cursor=cursor, page_size=20)   # 深分页推荐方案
```

### Q17. 缓存空值为什么要 set_empty？TTL 上限？

**问题**：查询不存在的 key 每次都打 DB（缓存穿透）。

**解决**：把「不存在」也缓存起来（空值占位），TTL 被钳制到 **[1, 120] 秒**（`EMPTY_TTL_LIMIT_SECONDS=120`），避免「不存在」状态长期驻留掩盖数据已新增（[07-缓存.md §4](./07-缓存.md#4-空值缓存防穿透set_empty--is_empty)）：

```python
if await cache.is_empty(key):      # 命中空值占位 → 直接短路
    return None
cached = await cache.get(key)
if cached is not None:
    return json.loads(cached)
row = await repo.get(key)
if row is None:
    await cache.set_empty(key, ttl=60)   # 空值占位（自动钳制 ≤120s）
    return None
await cache.set(key, json.dumps(row), ttl=300)
```

### Q18. 本地缓存 TTL 为什么比 Redis 短？

**问题**：`cache.set(key, v, ttl=300)` 后本地读取的 TTL 明显小于 300s。

**原因**：**本地 TTL 钳制**——本地缓存（内存）为加速层，其 TTL 被限制为分布式（Redis）TTL 的 `1/3`（`CacheConfig.local_ttl_ratio_limit=1/3`），避免本地缓存长期持有过期数据（[07-缓存.md §5](./07-缓存.md#5-ttl-抖动防雪崩与本地-ttl-钳制)）；Redis 本身为分布式存储，无钳制。

**解决**：无需处理，属预期行为；如需更长本地 TTL，调整 `CacheConfig` 钳制比例。

### Q19. 多租户缓存 Key？

**问题**：多租户场景不同租户缓存互相串数据。

**解决**：租户数据缓存必须经 `TenantKeyBuilder` 生成 Key（租户维度注入，隔离命名空间）；无租户上下文时回落 `no-tenant` 占位（[07-缓存.md §7](./07-缓存.md#7-租户隔离tenantkeybuilder)、[13-多租户.md](./13-多租户.md)）。Redis 缓存默认 Key 前缀 `web:`，真实 Key 如 `web:auth:v1:token:1001:xxxx`（[22-工具类与常量规范.md §10.3](./22-工具类与常量规范.md#103-缓存-key-模板-webmodulev1biz)）。

## 5. MQ / Outbox

### Q20. 消费失败重试与死信？

**问题**：消费者处理失败后消息去哪了？

**解决**：可重试异常（普通异常/`RetryableError`）按**指数退避**重试（`delay = retry_backoff_seconds × 2^(retry_count-1)`），超限进死信；`NonRetryableError` 不重试直接进死信；死信消息包裹原消息 ID/主题/biz_id/错误信息投递到 `dead_letter_topic`（[08-消息队列与Outbox.md §6](./08-消息队列与Outbox.md#6-重试分类retryableerror--nonretryableerror)）：

```python
async def handler(message: Message) -> None:
    if message.body.get("amount", 0) < 0:
        raise NonRetryableError("业务校验失败")   # 直接进死信
    ...  # 抛普通异常 → 指数退避重试，超限进死信
```

### Q21. 幂等消费用 biz_id 还是 msg_id？

**问题**：重复消费如何幂等？只按 msg_id 去重够吗？

**解决**：所有消费者必须以 **`bizId + msgId` 联合幂等**（保留 **7 天**，规范 §9.2），重复消费直接跳过视为 ACK。框架 `IdempotentConsumer` 先占幂等键再执行业务；多实例场景幂等存储必须用 Redis（SETNX 原子），内存实现在单进程内有效（[08 §5](./08-消息队列与Outbox.md#5-幂等消费idempotentconsumer)）。幂等 Key 模板见 [22-工具类与常量规范.md §10.3](./22-工具类与常量规范.md#103-缓存-key-模板-webmodulev1biz)（`web:mq:v1:msg_idem:{key}`）。

### Q22. Outbox 怎么保证不丢消息？

**问题**：业务写库成功后发消息失败，消息丢了怎么办？

**解决**：**Outbox 本地事务表**实现「业务写库 + 发消息」最终一致性可靠投递：业务数据与 outbox 记录在**同一本地事务**写入 → 后台任务轮询投递 → 投递成功标记 → 失败按指数退避重试（超限进死信）→ 定期清理（保留 7 天）（[08 §7](./08-消息队列与Outbox.md#7-outbox-可靠投递全流程)）。需显式调用 `register_outbox_tasks` 装配定时任务：

```yaml
app:
  mq:
    outbox:
      enabled: true          # 供业务配置参考（由 register_outbox_tasks 装配）
      max_retry: 3
      dead_letter_topic: web-dlq-topic
```

### Q23. 多实例定时任务防重？

**问题**：多实例部署时定时任务每个实例都执行，重复处理。

**解决**：`TaskScheduler` 内置**分布式锁防重复** + 执行记录 + 失败退避（[11-定时任务与异步任务.md](./11-定时任务与异步任务.md)）；分布式锁用 Redis 实现（`app.cache.type: redis`），多实例必须启用 Redis，内存锁仅单实例有效（[14-韧性设计.md](./14-韧性设计.md)）。

## 6. 认证与权限

### Q24. 多实例登出/凭证复用失效？

**问题**：多实例部署后，A 实例登出的 token 在 B 实例仍有效；同设备新登录旧凭证不失效。

**原因**：Token 状态存储默认 `InMemoryJwtTokenStore`（进程内状态），多实例无法共享。

**解决**：多实例必须使用 **Redis 状态存储**——框架装配时若启用 Redis（`app.cache.type: redis`）会自动注入（`JWTUtil.set_redis_config`），无需手动调用；也可显式 `configure` 自定义 store。自动回落规则：显式 configure > set_redis > 框架 Redis > 内存（[12-认证与安全.md §2.2](./12-认证与安全.md#22-配置与装配)）。

### Q25. EXPIRING 静默刷新怎么处理？

**问题**：token 还没过期但校验返回 `EXPIRING`，要不要拒绝？

**原因**：剩余有效期低于阈值（300s）时返回 `EXPIRING`，这是**静默续期信号**，不是错误。

**解决**：`VALID` 与 `EXPIRING` 均放行；`EXPIRING` 时用 refresh token 换取新 access token，实现无感续期（[12 §2.3](./12-认证与安全.md#23-代码示例)）：

```python
payload, status = await JWTUtil.verify_token(token)
if status in (TokenVerifyStatus.VALID, TokenVerifyStatus.EXPIRING):
    ...  # 放行；EXPIRING 时同步签发新 token
```

### Q26. PermissionGuard 的 admin 通配？

**问题**：管理员用户为什么能访问所有权限点接口？

**原因**：这是设计行为——Scope 为 `admin`（`AuthConstant.AUTH_SCOPE_ADMIN`）时**通配所有权限点**；权限点统一走 `AUTH_PERM_` 前缀常量，禁止裸字符串（[12 §4.1](./12-认证与安全.md#41-permissionguardrbac-声明式)、[22 §10.2](./22-工具类与常量规范.md#102-权限点-auth_perm-前缀)）。

```python
@router.get("/orders")
async def list_orders(_: None = Depends(PermissionGuard.require(AuthConstant.AUTH_PERM_ORDER_READ))):
    ...
```

### Q27. 社交登录绑定存储多实例问题？

**问题**：多实例部署后，用户在三方平台绑定/解绑状态不一致。

**原因**：`SocialLoginService` 默认注入 `InMemorySocialBindingStore`（进程内）。

**解决**：多实例部署把绑定存储换成 **Redis/数据库实现**（实现 `SocialBindingStore` 接口并注入），与 JWT 状态存储同理（[12 §7](./12-认证与安全.md#7-社交登录)）：

```python
service = SocialLoginService(registry, RedisSocialBindingStore(redis_client))  # 多实例必须替换 InMemory 实现
```

## 7. AI

### Q28. 新供应商怎么接入？

**问题**：要接入 DeepSeek / 智谱 / 通义 / 私有化部署等新模型。

**解决**：任何 **OpenAI 兼容端点零代码接入**——`provider: openai_compatible`（或缺省）即按 `api_base/api_key/model_id` 调用 `{api_base}/chat/completions` 与 `{api_base}/embeddings`；非 OpenAI 兼容协议需实现 `ModelProviderInterface` 并注册进 `ModelProviderRegistry`（[15-AI模型网关.md §6](./15-AI模型网关.md)）。

```yaml
app:
  ai:
    enabled: true
    store: { type: yml }
    models:
      - code: deepseek-v2-chat
        provider: openai_compatible
        api_base: https://api.deepseek.com/v1
        api_key: ${LLM_API_KEY:}
        model_id: deepseek-chat
```

### Q29. 调用报 E4-AI-001（模型/供应商未配置）？

**问题**：`gateway.chat(...)` 抛 `E4-AI-001`。

**原因**：场景路由未命中（无 `default_scene` 兜底）或模型未注册/不存在（[15 §7.1](./15-AI模型网关.md)）。

**解决**：检查 `app.ai.models` 模型清单与 `model_gateway.routes` 场景路由；yml 模式启动即注册，db 模式依赖 `ai_model_config` 表（初始化见 `db/init/ddl/002 + dml/002`）；注册失败不阻断启动，调用回落 E4-AI-001 明确报错。

### Q30. 内容审核 BLOCK 抛 E4-AI-002？

**问题**：输入/输出内容命中审核规则被拦截。

**原因**：这是**安全设计**——`RuleBasedContentGuard` 关键词命中 BLOCK 时抛 `E4-AI-002`（输出按 危险阻断/敏感警告 分级；`GuardAction` 枚举 BLOCK/WARN/PASS）；BLOCK 直接抛出，**不重试不降级**（[15 §7.1](./15-AI模型网关.md)）。

**解决**：确认审核规则是否符合业务（`block_rules`/`warn_rules` 参数可自定义）；若接入第三方审核服务，实现 `ContentGuardInterface` 整体替换。

### Q31. 流式中断的错误分片语义？

**问题**：流式对话中途报错，客户端怎么感知与恢复？

**解决**：**已产出分片后（AI-5）不再整体重试/降级**，而是产出统一流内错误分片 `ChatStreamChunk(error=<错误码>, finish_reason=ERROR)` 终止；消费到 `error` 分片即知中断原因（`WebInfraException` 用其错误码，其他异常统一 `E4-AI-004`）。**未产出任何分片前**的错误才走重试/降级（E3-THIRD-* 指数退避）（[15 §7.2](./15-AI模型网关.md#72-流式语义stream_chat)）。

### Q32. 配额超额 E4-AI-005？

**问题**：调用被 `E4-AI-005` 拒绝。

**原因**：模型网关级配额（租户维度）耗尽——`app.ai.quota` 的 `max_calls` / `max_tokens` / `max_cost`（0 表示不限）。

**解决**：调整配额或重置窗口；配额为「入口检查 + 用量累计」，超限由下次入口拦截（[15 §11](./15-AI模型网关.md#11-配额)）。

## 8. 支付

### Q33. 回调返回 401，渠道一直重试？

**问题**：微信回调返回 401，微信侧反复重推。

**原因**：**回调验签失败/报文解密失败**（`E3-PAY-001`）返回 401 是设计行为——渠道收到 401 会按协议重试，因此必须修到验签通过（[使用说明.md §4.1](../使用说明.md#41-支付能力)、[订单兜底策略.md](../订单兜底策略.md)）。

**解决**：核对 `app.payment.wechat` 的 `api_v3_key` / 私钥 / 证书配置；确认回调 URL 与商户号一致；验签通过前不要先执行业务逻辑。

### Q34. 回调金额不符 E4-PAY-002？

**问题**：回调金额与订单不符被拒。

**原因**：金额校验是**资金安全红线**——`Decimal` 精确比较回调 `amount` 与本地订单金额，不符抛 `E4-PAY-002`。

**解决**：排查订单金额被篡改或回调金额计算单位错误（分/元）；金额计算必须用 `Decimal`（`MathUtil.to_decimal`），禁止 `float` 直接比较（[22 §6](./22-工具类与常量规范.md#6-数学工具mathutil)）。

### Q35. 订单状态冲突 E4-PAY-003？

**问题**：重复回调/已关闭订单收到回调返回 409。

**原因**：状态机校验——重复回调或已关闭订单的非法状态迁移抛 `E4-PAY-003`（409），**终态不可逆**。

**解决**：这是幂等保护，属预期；确认无并发重复回调即可（渠道侧重试会持续触发，但状态不再变化）（[使用说明.md §4.1](../使用说明.md#41-支付能力)）。

### Q36. 平台证书自动下载与本地测试？

**问题**：`verify_mode: platform_cert` 验签遇未知序列号报错；本地无微信商户号怎么测试支付？

**解决**：

- 平台证书：`app.payment.wechat.cert_auto_download: true` 开启**自动下载**——验签遇未知序列号自动调 `/v3/certificates` 获取并缓存（默认关闭，需显式开启；也可手动放入 `platform_cert_dir`）；
- 本地测试：用框架内置测试工具——`InMemoryPaymentGateway`（骨架化内存渠道，注入 flow_store/order_store 即获全套兜底）+ `PaymentCallbackSimulator`（回调模拟器）+ `PaymentChannelContract`（9 个资金场景契约用例）（[使用说明.md §4.1](../使用说明.md#41-支付能力)）。

## 9. 部署与监控

### Q37. 生产访问 /metrics / /capacity 返回 403（E4-SYS-004）？

**问题**：生产环境浏览器访问 `/metrics` 或 `/capacity` 返回 403，错误码 `E4-SYS-004`。

**原因**：**诊断端点生产访问控制**——`APP_ENV=prod` 时默认启用 IP 白名单（精确 5 段内网 + `allowed_cidrs` 追加），外部 IP 拒绝 403；**fail-closed**（无法解析客户端 IP 也拒绝），防解析异常被利用绕过白名单（[21-监控与指标.md §8](./21-监控与指标.md#8-诊断访问守卫diagnosticaccessguard)）。

**解决**：将来源加入白名单（运维跳板机/监控网段）：

```yaml
app:
  diagnostics:
    access:
      enabled: true
      allowed_cidrs: ["10.0.0.0/8"]   # 追加白名单网段
```

### Q38. /metrics 指标为空 / 某分组不展示？

**问题**：`/metrics` 看不到缓存/MQ/存储/注册中心相关指标。

**原因**：组件指标为**懒注册**——仅在组件实际被调用（启用）时注册；未启用组件不产生任何指标，HTML 页面按样本动态渲染分组（[21 §3](./21-监控与指标.md#3-各组件指标懒注册)）。RED 指标来自访问日志中间件（需 `setup_logging_middleware` 装配），`service` 标签默认 `"app"`。

**解决**：确认组件已启用并产生过调用（`app.cache.type: redis` 且执行过读写）；RED 指标可经 `setup_logging_middleware(app, service_name=...)` 指定服务名。

### Q39. 优雅停机怎么配？

**问题**：滚动发布时存量请求被强杀/连接未排空。

**解决**：框架停机流程为「摘流量 → 等待窗口 → 连接排空与资源释放」（[application.py `_shutdown`](../../src/web_infra/core/application.py)）。配置等待窗口：

```yaml
app:
  graceful_shutdown_wait_seconds: 10   # 等待窗口（秒）；默认 0（保持旧行为），生产建议 ≥10s
```

> 注：该配置项由代码读取（默认 0），`application.default.yml` 未声明；同时需在部署层配合 K8s `preStop` / 注册中心下线摘流量。

### Q40. 日志怎么输出 JSON？

**问题**：生产日志希望结构化采集（ELK 等）。

**解决**：

```yaml
app:
  logging:
    level: INFO
    format: json        # text | json（JSON 携带 time/level/trace_id/module/user_id/error_code/message）
    output: both        # both | console | file
    file: ${APP_LOGGING_FILE:logs/app.log}
    retention_days: 30
```

错误日志约定：`logger.error(..., extra={"error_code": "E4-ORDER-001"})` 将错误码写入 JSON 的 `error_code` 字段（[05-请求上下文与日志.md §2](./05-请求上下文与日志.md#2-日志体系)）。自定义通道（如 Kafka/ELK）经 `LogSinkInterface` SPI 接入（`app.logging.sinks`）。

---

> 更多细节见对应能力文档；错误码/常量查询见 [常量与错误码.md](../常量与错误码.md)；扩展点契约见 [SPI-Extensions.md](../SPI-Extensions.md)。
