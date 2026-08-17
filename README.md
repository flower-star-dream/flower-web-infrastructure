# flower web 通用框架（flower-web-infrastructure）

[![version](https://img.shields.io/badge/version-v0.1.0-blue)](https://github.com/flower-star-dream/flower-web-infrastructure)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://github.com/flower-star-dream/flower-web-infrastructure)
[![license](https://img.shields.io/badge/license-MIT-green)](https://github.com/flower-star-dream/flower-web-infrastructure)
[![CI](https://img.shields.io/github/actions/workflow/status/flower-star-dream/flower-web-infrastructure/ci.yml?label=CI&logo=github)](https://github.com/flower-star-dream/flower-web-infrastructure/actions)

> 配置驱动的 Web 系统通用后端基础设施 —— 单体 / 微服务通用基础依赖，开箱即用。

| 项目     | 值                                              |
| -------- | ----------------------------------------------- |
| 当前版本 | v0.1.0                                          |
| Python   | >= 3.10                                         |
| License  | MIT                                             |
| 构建     | [GitHub Actions](./.github/workflows/ci.yml)    |

## 目录

- [1. 简介](#1-简介)
- [2. 功能特性](#2-功能特性)
- [3. 技术栈](#3-技术栈)
- [4. 安装](#4-安装)
- [5. 快速开始](#5-快速开始)
- [6. 配置说明](#6-配置说明)
- [7. 常用功能示例](#7-常用功能示例)
- [8. 项目结构](#8-项目结构)
- [9. 测试](#9-测试)
- [10. Docker 镜像](#10-docker-镜像)
- [11. CI/CD](#11-cicd)
- [12. 相关文档](#12-相关文档)
- [13. 版本与兼容性](#13-版本与兼容性)
- [14. 许可证](#14-许可证)

## 1. 简介

flower web 通用框架是一套**配置驱动**的后端基础设施库，面向单体与微服务场景，统一封装业务开发中的高频能力：

- 统一响应结构、错误码体系与全局异常处理；
- 认证鉴权（JWT / RBAC / OAuth2）、幂等、验证码、登录防爆破；
- 缓存、数据库、消息队列（含 Outbox 可靠投递）、对象存储、服务注册发现；
- 定时任务、异步任务、韧性设计（重试 / 熔断 / 限流 / 分布式锁）；
- AI 模型网关（模型自动注册、场景路由、主备降级、配额计费）与 RAG 检索能力；
- 多租户（上下文校验、缓存隔离、SQL 自动注入租户条件、多数据源动态路由）。

业务项目通过 `create_app` 自动装配组件，按需通过 YAML 配置启用 / 关闭中间件与组件，**无需在业务代码中重复封装**。各能力遵循「抽象接口 + 默认实现 + 真实实现」模式，业务只依赖抽象接口，通过配置切换实现。框架预留的全部 SPI 扩展点清单与方法契约见 [SPI 扩展点文档](./docs/SPI-Extensions.md)。

## 2. 功能特性

| 能力            | 说明                                                                                                                                                                                        |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 应用启动器      | `Application` / `create_app` 配置驱动自动装配（Spring Boot 风格）                                                                                                                       |
| 统一响应结构    | `Result` / `PageResult`，统一 `code + message + data` 返回格式                                                                                                                        |
| 错误码体系      | 错误码定义、解析、边界收敛（E3/E5 收敛为大类码），`BizException` + 全局异常处理                                                                                                           |
| 请求上下文      | 基于`contextvars` 的 TraceId / 用户 / 租户 / 客户端上下文，跨异步自动透传                                                                                                                 |
| 日志            | 文本/JSON 格式 + 敏感信息脱敏 + TraceId 贯穿链路                                                                                                                                            |
| 通用配置        | YAML 多源配置（环境变量 > application.yml > 框架默认），支持 Nacos 配置中心                                                                                                                 |
| 缓存            | `CacheBackend` 抽象 + 内存 / Redis 实现，租户维度 Key 构建；空值缓存防穿透（TTL≤120s）+ TTL 随机抖动防雪崩 + 本地缓存 TTL 钳制（分布式 1/3） |
| 数据库          | MySQL（SQLAlchemy）/ MongoDB / Redis / SQLite；`session()`（通用接口）/ `orm_session()`（ORM 模型查询）自动管理生命周期（提交/回滚/关闭），业务无 try/finally                           |
| 消息队列        | `MessagePublisher` / `MessageConsumer` 抽象 + 内存 / RocketMQ 实现                                                                                                                      |
| Outbox 可靠投递 | 本地事务表 + 轮询投递 + 指数退避重试 + 死信队列（DLQ）+ 7 天清理；内存 / MySQL 双存储，消费幂等去重、异常分类重试                                                                                                                                              |
| 定时任务调度    | asyncio 调度 + 可选分布式锁防多实例重复 + 超时/连续失败暂停                                                                                                                                 |
| 对象存储        | `ObjectStorage` 抽象 + 本地 / MinIO 实现，分片上传/断点续传                                                                                                                               |
| 服务注册发现    | `ServiceRegistry` 抽象 + 内存 / Nacos 实现，负载均衡与 Feign 调用                                                                                                                         |
| 韧性设计        | 重试（指数退避）、熔断、令牌桶限流、Redis 分布式锁                                                                                                                                          |
| 认证与安全      | JWT 签发校验/登出、密码加密、图形验证码、登录防爆破锁定（**认证/鉴权能力依赖用户系统（业务实现），默认关闭**，见 [6 配置说明](#6-配置说明)） |
| 统一鉴权中间件  | 统一入口 Bearer 校验 + 白名单 + 上下文注入，RBAC 声明式权限守卫（默认关闭，需显式启用） |
| API 幂等键      | 写接口幂等键占用 + 结果缓存（内存/Redis），重复请求返回首次结果                                                                                                                             |
| OAuth2          | 客户端注册 SPI + 令牌签发/校验/撤销（client_credentials 最小实现）                                                                                                                          |
| AI 供应商抽象   | Provider SPI + 统一出入参 + 模型配置管理                                                                                                                                                    |
| 模型自动注册    | 配置清单（yml/页面化配置）自动注册供应商，默认 OpenAI 兼容协议，自定义协议 SPI 接入                                                                                                         |
| 统一模型网关    | 场景路由 + 主备降级 + 连接池分池 + 可重试退避重试（幂等键复用）+ TTFT/全量超时 + 并发控制 + 三维度配额（租户/用户/场景）+ 模型权限校验 SPI + 流内错误分片 + 计费 + 指标 |
| Prompt 管理     | 模板版本化 + 参数化注入（防注入）+ 角色隔离                                                                                                                                                 |
| 向量检索        | 切片 / Embedding（内置哈希嵌入默认实现）/ 向量库 SPI / Rerank / 阈值过滤（默认 0.75，低相关降级）/ 降级                                                                                                                                    |
| AI 缓存         | SHA-256 Key（含模型版本/租户），版本变更自动失效                                                                                                                                            |
| SSE 流式        | 统一分片 + 心跳保活 + 客户端断开取消传播 + 流内错误分片                                                                                                                                     |
| 内容安全审核    | 输入阻断 / 输出分级审核扩展点 + 默认规则实现，已接入模型网关调用链（BLOCK 抛 E4-AI-002）                                                                                                   |
| 异步任务框架    | 任务状态机 + 心跳 + 死任务扫描 + 乐观锁终态保护                                                                                                                                             |
| 多租户          | 租户上下文校验 + 缓存 Key 租户维度 + SQLAlchemy 条件自动注入 + 多数据源动态路由                                                                                                             |
| 分片上传        | 初始化/逐片/断点续传/合并校验（MD5+大小），本地 + MinIO 双实现                                                                                                                              |
| 健康检查/指标   | `/health`（组件连通性探测）+ `/metrics`（Prometheus 文本 + 浏览器 HTML 可视化；连接池/运行时/线程池/缓存/存储/消息队列/注册中心组件指标，按组件启用配置动态采集与展示，自定义分组 SPI） |
| 支付能力        | 渠道 SPI + 骨架兜底（下单幂等/关单确认/回调校验/流水落库）+ 微信渠道 + 超时关单 + 对账/冲正 + 风控限额 + 审计/权限点；**可选能力**：不随顶层导出，依赖 鉴权→认证→用户系统（业务实现），按需主动引入（见 [7.12 支付](#712-支付) / [docs/使用说明.md 4.2](./docs/使用说明.md#42-能力依赖与装配)） |
| 能力注册表      | `CapabilityRegistry`：能力契约（SPI）+ 依赖包含规则 + 装配校验；依赖链 用户系统→认证→鉴权→支付，启用按包含关系自动带上前置（`app.capabilities.enabled` 声明，见 [docs/使用说明.md 4.2](./docs/使用说明.md#42-能力依赖与装配)） |
| 通用工具        | 雪花 ID、日期、文件锁、数学、Token 精确计数、PDF 渲染                                                                                                                                    |

## 3. 技术栈

| 分类        | 技术                                                       |
| ----------- | ---------------------------------------------------------- |
| 语言/运行时 | Python >= 3.10，asyncio                                    |
| Web 框架    | FastAPI、Uvicorn、Pydantic v2                              |
| 数据库      | SQLAlchemy 2.0（MySQL / SQLite）、Redis、MongoDB（Beanie） |
| 消息队列    | RocketMQ（可选，延迟导入）、内存实现                       |
| 对象存储    | MinIO（可选，延迟导入）、本地文件系统                      |
| 注册发现    | Nacos（可选，延迟导入）、内存实现                          |
| 观测        | Prometheus client、结构化日志（JSON / 文本 + 脱敏）        |
| 质量        | pytest、pytest-asyncio、pyright（静态类型检查）            |
| 交付        | Docker（基础镜像）、GitHub Actions（CI/CD）                |

## 4. 安装

> 建议在项目内创建虚拟环境，避免全局安装。

```bash
# 创建并激活虚拟环境（Windows）
python -m venv .venv
.venv\Scripts\activate
```

**最小安装（推荐，仅核心依赖）**——Web / 配置 / 日志 / 错误码 / 安全工具类（JWT、密码加密）/ 缓存（内存）/ 监控 / 韧性，`import web_infra` 与 `create_app()` 开箱即用；**不含** MySQL/Redis/Mongo 数据访问（代码延迟导入）及 MinIO / Nacos / RocketMQ / Alembic / RAG / PDF 等可选组件。数据库与缓存扩展能力需按需安装 extras（见下方"按需追加可选能力"）。**依赖链上的业务可选能力（用户系统 → 认证 → 鉴权 → 支付）默认全部关闭**（认证/鉴权与支付一样依赖用户系统，`app.capabilities.enabled` 默认空，见 [docs/使用说明.md](./docs/使用说明.md) 1.1/4.2 节）：

```bash
pip install flower-web-infrastructure
```

> `from web_infra import *` 兼容最小安装（不触发可选依赖加载）；已安装 mysql/redis/mongo 对应 extras 时自动全量导出（含 `Base`/`MySQLConfig`/`RedisConfig` 等），最小安装下这些组件需先装 extras 后显式导入。

**最小单体 / 最小微服务（安装即用）**——按架构形态二选一，安装后复制 [docs/使用说明.md](./docs/使用说明.md) 1.2 节的 `application.yml` 模板即可启动：

```bash
pip install "flower-web-infrastructure[min-monolith]"       # 单体：核心 + MySQL/SQLite + Redis（无外部 broker）
pip install "flower-web-infrastructure[min-microservice]"   # 微服务：核心 + MySQL + Redis + Nacos + RocketMQ + MinIO
```

**全量安装**（核心 + 全部可选能力，适合开发环境）：

```bash
pip install "flower-web-infrastructure[all]"
```

**按需追加可选能力**（见 [docs/使用说明.md](./docs/使用说明.md) 第 5 节依赖对照表）：

```bash
pip install "flower-web-infrastructure[mysql]"              # MySQL/SQLite ORM 数据访问
pip install "flower-web-infrastructure[redis]"              # Redis 缓存/分布式锁/幂等存储
pip install "flower-web-infrastructure[mongo]"              # MongoDB 数据访问
pip install "flower-web-infrastructure[storage]"            # MinIO 对象存储
pip install "flower-web-infrastructure[migrate]"            # Alembic 迁移工具
pip install "flower-web-infrastructure[nacos,rocketmq]"     # 配置中心 + RocketMQ
pip install "flower-web-infrastructure[rag]"                # 向量检索（faiss + sentence-transformers）
pip install "flower-web-infrastructure[pdf]"                # PDF 渲染导出（playwright）
```

**本地开发安装**（框架与业务同机，editable 即时生效）：

```bash
pip install -e "f:\baseProject\flower-web-infrastructure[all]"
```

可选能力依赖（延迟导入，不安装不影响核心功能）说明：Nacos（官方 nacos-sdk-python v2，gRPC 协议）与 RocketMQ 按需安装；RAG / PDF 为重量级可选能力。

## 5. 快速开始

推荐通过 `create_app` 启动项目，自动装配日志、中间件、异常处理与各组件：

```python
from web_infra import create_app, Result, CommonErrorCode

# settings 参数为可选覆盖层（dict 优先级高于 YAML），配置主来源仍是 application.yml
app = create_app({"app.name": "demo"})

@app.get("/v1/orders/{order_id}")
def get_order(order_id: str):
    if order_id == "0":
        raise CommonErrorCode.COMMON_NOT_FOUND.to_exception()
    return Result.success(data={"orderId": order_id})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

响应示例：

```json
{ "code": "S0000", "message": "ok", "data": { "orderId": "1001" } }
```

## 6. 配置说明

配置统一走 YAML，优先级为「环境变量 > 项目根目录 `application.yml` > 框架默认 `application.default.yml`」。默认配置不散落在代码中，`application.py` 不内嵌默认值；中间件/多租户/AI 等特殊能力默认关闭，由业务配置显式开启。

YAML 中支持 `${ENV}` / `${ENV:default}` 环境变量占位符（未定义时取默认值，未定义且无默认值保留原样），敏感配置（如数据库密码）可写为 `${APP_DB_MYSQL_PASSWORD}` 经环境变量注入，避免明文随 yml 提交仓库。**推荐做法（框架已内置）**：框架默认配置中的敏感项（MySQL/Redis/MongoDB 账号密码、MinIO/Nacos 访问密钥）均已用 `${ENV:default}` 引用环境变量，业务项目只需将敏感值写入项目根 `.env`（如 `APP_DB_MYSQL_PASSWORD=xxx`）即可生效，无需修改 yml。框架启动时自动加载项目根 `.env`（`.env` 默认已被 `.gitignore` 忽略，复制 `.env.example` 填写即可），已存在的进程/容器环境变量优先、不被 `.env` 覆盖。

`application.yml` 示例（项目根目录）：

```yaml
app:
  name: demo
  logging:
    level: INFO
    format: text
  capabilities:           # 能力装配（可选能力依赖包含规则，默认空 = 业务可选能力链全部关闭）
    enabled: []           # 如 [pay] 自动启用 鉴权(authz)→认证(authn)→用户系统(user)（业务实现由业务层提供）
  web:
    middlewares:            # 中间件声明式引入：列出即引入，enabled: false 显式关闭
      idempotency:
        enabled: false
        ttl_seconds: 86400
      auth:
        enabled: false      # 需使用时改为 true 并配置白名单
        whitelist: ["/health", "/metrics", "/docs", "/redoc", "/openapi.json"]
      trace_id: {}          # 默认引入，需最后声明（最先执行生成 TraceId，避免覆盖内层鉴权注入的身份）
  cache:
    type: memory             # memory / redis
  db:
    type: mysql              # mysql / sqlite
    mysql:
      host: 127.0.0.1
      port: 3306
      database: demo
      # 敏感配置（账号/密码）推荐写入环境变量/.env，yml 中以 ${ENV:default} 引用
      username: ${APP_DB_MYSQL_USERNAME:root}
      password: ${APP_DB_MYSQL_PASSWORD:}
  storage:
    type: local              # local / minio
    base_dir: ./data
  mq:
    type: memory             # memory / rocketmq
  registry:
    type: memory             # memory / nacos
```

关键配置项：

| 配置键                  | 可选值（默认加粗）          | 说明                                             |
| ----------------------- | --------------------------- | ------------------------------------------------ |
| `app.capabilities.enabled` | **[]** / 能力名列表    | 能力装配：声明启用的能力（user / authn / authz / pay 等），装配时按依赖包含规则校验并自动带上前置（未知能力/循环抛 ConfigError）；默认空 = 业务可选能力链全部关闭 |
| `app.web.middlewares` | 声明式清单                  | trace_id 默认引入；auth / idempotency 需自行启用 |
| `app.cache.type`      | **memory** / redis    | 缓存实现切换                                     |
| `app.db.type`         | **mysql** / sqlite    | 数据库实现切换                                   |
| `app.db.sqlite.path`  | ./data.db             | SQLite 数据库文件路径（`app.db.type=sqlite` 时生效） |
| `app.env`             | **dev** / test / stage / prod | 环境标识（优先读 `APP_ENV` 环境变量；未显式指定时 warning；`is_production()` 判断，规范 §19.3） |
| `app.mongo.enabled`   | **false** / true      | MongoDB 组件开关                                 |
| `app.ai.enabled`      | **false** / true      | AI 模型网关开关（特殊场景默认关闭）              |
| `app.tenant.enabled`  | **false** / true      | 多租户开关（特殊场景默认关闭）                   |
| `app.storage.type`    | **local** / minio     | 对象存储切换                                     |
| `app.mq.type`         | **memory** / rocketmq | 消息队列切换                                     |
| `app.registry.type`   | **memory** / nacos    | 注册发现切换                                     |

已装配组件通过 `app.state.<name>` 访问（cache / db / mongo / storage / mq / registry / ai / ai_registrar）。

## 7. 常用功能示例

### 7.1 统一响应与业务异常

```python
from web_infra import Result, PageResult, CommonErrorCode

# 成功
return Result.success(data={"orderId": "1001"})
# 分页（data.list + data.total）
return PageResult.success(records=[...], total=100)
# 业务异常（统一抛出约定：错误码.to_exception()，全局异常处理自动转换为统一错误响应）
raise CommonErrorCode.PARAM_INVALID.to_exception(message="订单号不能为空")
```

### 7.2 日志与请求上下文

```python
from web_infra import get_logger, RequestContext

logger = get_logger("order.service")
logger.info("创建订单 user=%s order=%s", RequestContext.get_user_id(), order_id)
```

### 7.3 缓存

```python
from web_infra import CacheBackendInterface, MemoryCacheBackend, KeyBuilder

cache: CacheBackendInterface = MemoryCacheBackend()
await cache.set("order:1001", {"status": "paid"}, ttl=3600)
data = await cache.get("order:1001")

# 防缓存穿透（规范 §8.2）：数据不存在时写空值占位（TTL ≤ 120s），未命中与空值区分
await cache.set_empty("order:not-exist", ttl=60)
assert await cache.is_empty("order:not-exist") is True   # 空值占位 → 不再直打 DB

# 防缓存雪崩（规范 §8.3）：热点 Key 可开启 TTL 随机抖动（0~5s 叠加），同 TTL 错峰过期
await cache.set("hot:rank", data, ttl=300, ttl_jitter_seconds=5)
```

### 7.4 数据库（会话生命周期自动管理）

数据库访问统一走框架会话封装（规范 §10.6：禁止业务代码裸获取连接），`session()` / `orm_session()` 自动完成「创建 → 提交/回滚 → 关闭」，业务代码无需手写 try/finally。**使用原则：拥有 ORM 框架的数据库（如 MySQL/SQLAlchemy）强制走 ORM 会话；无 ORM 框架的数据库（如 SQLite 轻量工厂）直接封装使用即可，不强制实现 `orm_session()`。**

**方式一：通用会话接口（文本 SQL，MySQL / SQLite 通用）**

```python
from fastapi import Depends
from web_infra import provide_db_session

db = app.state.db   # 已装配的数据库工厂（MySQLDatabase / DatabaseManager）

# async with（推荐）—— 退出自动提交，异常自动回滚并关闭
async with db.session() as session:
    rows = await session.query_all("SELECT * FROM t_order WHERE id = :id", {"id": 1001})

# FastAPI 依赖注入 —— 框架自动管理会话生命周期
@app.get("/orders/{order_id}")
async def get_order(order_id: int, session=Depends(provide_db_session(db))):
    return await session.query_one("SELECT * FROM t_order WHERE id = :id", {"id": order_id})
```

**方式二：SQLAlchemy ORM（拥有 ORM 框架的数据库强制使用）**

业务模型继承框架导出的 `Base`，通过 `db.orm_session()` 获取原生 `AsyncSession`（适用于 MySQL 等 SQLAlchemy 场景）：

```python
from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, mapped_column
from web_infra import Base

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="created")

# orm_session()：退出自动提交（异常回滚）并关闭，无需 try/finally
async with db.orm_session() as session:
    session.add(Order(order_no="NO-1001", status="paid"))
    await session.flush()
    order = await session.get(Order, 1)
    paid_orders = (await session.execute(select(Order).where(Order.status == "paid"))).scalars().all()
```

**方式三：SQLite 轻量场景（sqlite3 直接封装使用）**

`SqliteSessionFactory` 基于 sqlite3 直接封装（无 ORM 框架，不强制 `orm_session()`），适合单体轻量/测试场景。**数据库配置统一走 yml，禁止硬编码 db_path**：

```yaml
# application.yml
app:
  db:
    type: sqlite                  # mysql / sqlite
    sqlite:
      path: ./data.db             # 数据库文件路径（由配置统一管理）
```

```python
db = app.state.db   # app.db.type=sqlite 时自动装配为 SqliteSessionFactory，db_path 来自 yml

# 退出自动提交（异常自动回滚）并关闭；sqlite3 占位符使用 ?
async with db.session() as session:
    session.execute("CREATE TABLE IF NOT EXISTS t_order (id INTEGER PRIMARY KEY, order_no TEXT, status TEXT)")
    session.execute("INSERT INTO t_order (order_no, status) VALUES (?, ?)", ("NO-1001", "paid"))
    rows = session.query_all("SELECT * FROM t_order WHERE status = ?", ("paid",))
```

多数据源（`DatabaseManager`）同样支持：`db.orm_session(name="ds1")` 指定数据源名。

**分页（规范 §12.3 / S10-1：禁止深分页，推荐游标分页）**

```python
from web_infra.db.page_query import PageQuery, CursorPageQuery

# 普通分页：page_no × page_size 超过 10000 时框架直接抛 ValueError 拒绝（S10-1 禁止 LIMIT offset 深分页）
query = PageQuery(page_no=1, page_size=20)

# 游标分页（推荐）：首页 cursor 传 None，后续页携带上一页返回的游标值（如最后一条记录 id/时间戳）
cursor_query = CursorPageQuery(cursor="20260815000001", page_size=20)
# 业务按排序字段生成游标比较条件，如 where_gt: col > :cursor（升序）或 where_lt: col < :cursor（降序）
```

**读写分离（规范 S10-2：读流量路由从库，写走主库）**

```python
from web_infra.db import MySQLConfig, MySQLDatabase

config = MySQLConfig(
    url="mysql+aiomysql://user:pwd@主库:3306/app",
    replica_urls=["mysql+aiomysql://user:pwd@从库1:3306/app", "mysql+aiomysql://user:pwd@从库2:3306/app"],
    # replica_username / replica_password 可选，缺省复用主库账号
)
db = MySQLDatabase(config)

# 读流量：read_replica=True 时 orm_session 自动路由到从库（轮询 replica_0/replica_1...），无从库时回退主库
async with db.orm_session(read_replica=True) as session:
    orders = (await session.execute(select(Order))).scalars().all()

# 写流量：默认走主库
async with db.orm_session() as session:
    session.add(Order(order_no="NO-1002", status="paid"))
```

### 7.5 消息队列与 Outbox

```python
from web_infra import (
    Message, InMemoryOutboxStore, MysqlOutboxStore, OutboxPublisher,
    IdempotentConsumer, InMemoryMessageIdempotencyStore, RetryableConsumer,
    DlqConsumer, requeue_dlq_to_outbox, register_outbox_tasks, MqConfig, TaskScheduler,
)

# 本地事务内追加 Outbox 消息，由定时任务轮询投递
store = InMemoryOutboxStore()                      # 单实例；多实例换 MysqlOutboxStore(session_factory)
await store.append(OutboxRecord(topic="order", biz_id="order-1001", payload={"orderId": "1001"}))

# 投递：失败按指数退避重试（MqConfig.retry_backoff_seconds 为基数），重试超限投递死信队列并置死信状态
config = MqConfig(max_retry=3, retry_backoff_seconds=30, dead_letter_topic="web-dlq-topic")
publisher = OutboxPublisher(store, mq_publisher, config=config)   # mq_publisher 为 MessagePublisherInterface
await publisher.publish_pending()

# Outbox 轮询投递 + 清理定时任务装配（S21-2，任务命名 message-outbox-publish / message-outbox-cleanup）
scheduler = TaskScheduler()
register_outbox_tasks(scheduler, store, mq_publisher, config=config,
                      publish_interval_seconds=5, cleanup_interval_seconds=3600)
scheduler.start()

# 死信消费治理（P0-3/S9-7）：订阅死信主题，on_dlq 钩子可重投递回 Outbox 或丢弃
dlq_consumer = DlqConsumer(mq_consumer, dlq_topic=config.dead_letter_topic,
                           on_dlq=lambda m: requeue_dlq_to_outbox(store, m))
await dlq_consumer.start()
```

> **生产接入 RocketMQ（P0-3 落地说明）**：`OutboxPublisher`/`DlqConsumer` 均接受任意 `MessagePublisherInterface`/`MessageConsumerInterface` 实现——生产环境将上述 `mq_publisher`/`mq_consumer` 替换为 `RocketMqPublisher`/RocketMQ 消费者（`RocketMqPublisher` 已实现分区选择与延迟消息），`MqConfig.dead_letter_topic` 配置死信主题即可完成 DLQ 生产接入；消息类型为 `web-dlq-topic` 的死信消息由 `DlqConsumer` 订阅治理（重投递/丢弃/告警）。

> **分区与延迟消息（规范 §9.2/§9.5）**：`Message(partition_key=业务主键)` 时发布端按稳定哈希选分区（分区内串行消费，`RocketMqPublisher` 默认 `HashMessageQueueSelector`）；`send_delay` 在 RocketMQ 实现中映射官方固定 delay level（1s~2h 共 18 档，禁止 sleep）。

# 消费端幂等（bizId 核心去重，业务失败自动回滚允许重试）
consumer = IdempotentConsumer(InMemoryMessageIdempotencyStore())
async def handler(message: Message) -> None:
    ...
await consumer.consume(message, handler)

# 消费异常分类重试（S9-1）：NonRetryableError 直接进 DLQ；可重试异常指数退避，超限进 DLQ
retryable = RetryableConsumer(mq_publisher, max_retries=3, retry_backoff_seconds=5,
                              dlq_topic=config.dead_letter_topic)
async def guarded(message: Message) -> None:
    await consumer.consume(message, handler)
await retryable.consume(message, guarded)
```

### 7.6 定时任务

```python
from web_infra import TaskScheduler

scheduler = TaskScheduler(lock_factory=lambda name: DistributedLock(redis, f"sched:{name}"))

async def sync_report() -> None:
    ...

scheduler.register_task(
    name="report:job:sync", module="report", interval_seconds=300,
    handler=sync_report, timeout_seconds=60, description="同步报表",
)
scheduler.start()   # 应用启动时调用
```

### 7.7 鉴权与 RBAC、API 幂等

```python
from fastapi import Depends
from web_infra import AuthConstant, PermissionGuard, DataPermissionGuard, JWTUtil

# 配置启用 auth 中间件后，接口声明权限点（权限走常量，校验失败返回 E2-PERM-000）
@app.post("/v1/orders", dependencies=[Depends(PermissionGuard.require(AuthConstant.AUTH_PERM_ORDER_WRITE))])
async def create_order():
    ...

# 水平越权防护（规范 §25.2）：查询/修改前校验资源属主，越权抛 E2-PERM-000
DataPermissionGuard.check(owner_id=row.owner_id, required_owner_id=row.owner_id,
                          current_user_id=RequestContext.get_user_id())

# 静默刷新（规范 §6.1）：凭证剩余有效期 < 300s 时 verify 返回 TokenVerifyStatus.EXPIRING（与 VALID 同放行），
# 客户端据此凭 refresh token（create_refresh_token / verify_refresh_token）静默续期，不打断会话。
```

### 7.8 AI 模型网关

模型无需代码手动注册：在 `application.yml` 的 `app.ai` 配置模型清单，应用启动时自动注册供应商并装配网关；默认支持 OpenAI 兼容协议（`/v1/chat/completions`），私有化/自建供应商经供应商 SPI 接入。

模型配置来源两套方案（`app.ai.store.type`，默认 `yml`）：
- `yml`：`app.ai.models` 清单在代码/配置中写死供应商与模型，启动即注册（下方示例）；
- `db`：模型配置入库 `ai_model_config` 表（框架内置 `SqlAlchemyModelConfigStore`，基线 DDL/DML 见 `db/init/ddl/002` 与 `db/init/dml/002`），启动生命周期自动同步注册；`api_key` 列仅存 `env:VAR` 引用，真实密钥经环境变量/.env 注入（如 `LLM_API_KEY=sk-xxx`），禁止明文落盘。

```yaml
app:
  ai:
    enabled: true                      # AI 模型网关开关（默认 false）
    models:                            # 模型清单：自动注册供应商，无需业务代码手动 register
      - id: 1
        model_name: DeepSeek Chat
        model_code: deepseek-chat      # 模型逻辑名（业务代码引用）
        provider: openai_compatible    # 协议：缺省回落 openai_compatible
        api_base: https://api.deepseek.com/v1
        api_key: sk-xxxx
        model_id: deepseek-chat        # 厂商侧真实模型 ID（缺省用 model_code）
        temperature: 0.0
      - id: 2
        model_name: 本地 Qwen
        model_code: local-qwen
        provider: openai_compatible
        api_base: http://localhost:8000/v1
        api_key: not-needed
    model_gateway:
      default_scene: chat
      routes:                          # 场景路由：主模型 + 备用模型（主失败降级）
        chat: { primary: deepseek-chat, backups: [local-qwen] }
        rag:  { primary: local-qwen, backups: [] }
```

业务代码只依赖统一出入参，调用逻辑名：

```python
from web_infra import ChatRequest, ChatMessage, ChatRole

gateway = app.state.ai                       # create_app 自动装配的模型网关
response = await gateway.chat(
    ChatRequest(model="deepseek-chat", messages=[ChatMessage(role=ChatRole.USER, content="你好")]),
    scene="chat", tenant_id="t1",
)
```

自定义供应商：实现 `ModelProviderInterface`，注册工厂后按 `provider` 字段自动装配（无需手动注册）：

```python
from web_infra import ModelProviderFactory

ModelProviderFactory.register_factory("my-vendor", lambda config: MyVendorProvider(config))
```

页面化模型配置：框架内置数据库实现 `SqlAlchemyModelConfigStore`（`app.ai.store.type=db` 自动装配，启动同步 SPI 注册表，页面化新增/修改经 `upsert` 幂等落库）；也可自定义 `ModelConfigStoreInterface`（配置中心等），启动时手动同步：

```python
async def startup():
    await app.state.ai_registrar.register_from_store(DbModelConfigStore())
```

**网关能力补充（整改 AI-2/3/5/8）**：

- **配额检查**：chat / stream_chat / embed 三入口统一检查，支持 **租户 / 用户 / 场景** 三维度（配额超限返回 `E1-RATE-000`，成本预算耗尽 `E4-AI-005`）；
- **模型权限 SPI（AI-8）**：`ModelGateway(..., access_policy=MyPolicy())` 注入 RBAC 策略（默认 `AllowAllModelAccessPolicy` 放行），无权限抛 `E2-PERM-000`；
- **流内错误分片（AI-5）**：流式响应产出部分分片后出错，不中断连接，统一产出 `ChatStreamChunk(error=错误码, finish_reason=ERROR)` 终止分片（未产出分片前仍抛异常供重试/降级）；`API Key` 支持 `env:VAR` 环境变量引用（`api_key: "env:LLM_API_KEY"`），禁止明文落盘。

### 7.9 多租户

```python
from web_infra import TenantGuard, TenantAwareMixin, TenantQueryFilter, RequestContext

# 模型继承 TenantAwareMixin 后，挂载 TenantQueryFilter 自动注入 tenant_id 条件
class Order(TenantAwareMixin, Base):
    __tablename__ = "orders"
    ...

filter = TenantQueryFilter(strict=True)   # strict：无租户上下文拒绝执行
filter.install(session_factory)            # SQLAlchemy session_factory

RequestContext.set_tenant_id("t1")         # 请求入口注入（X-Tenant-Id 头）
```

### 7.10 分片上传

```python
from web_infra import MultipartUploadService, InMemoryUploadStore, LocalPartStorage

upload = MultipartUploadService(InMemoryUploadStore(), LocalPartStorage("./tmp/parts"))

task = await upload.initialize("video.mp4", file_size=1024 * 1024 * 200, chunk_size=5 * 1024 * 1024)
await upload.upload_part(task.upload_id, 1, part_bytes)
done = await upload.list_uploaded_parts(task.upload_id)     # 断点续传：查询已传分片
object_key = await upload.complete(task.upload_id, expected_md5=md5)  # 合并校验后返回对象 Key
```

### 7.11 状态机

框架级通用状态机组件（`web_infra/state_machine/`）。引擎只做「流转合法性校验 + 事件分发」，不触碰持久层（持久化由路由处理器完成）。

**声明状态与事件**：状态/事件为**任意 hashable 值**（不限枚举）；`BaseState`/`BaseEvent` 是推荐便捷基类
（成员 value 即业务码，`description` 为中文名，`of(code)` 反查）：

```python
from web_infra import BaseState, BaseEvent

class OrderStatus(BaseState):
    PENDING_PAYMENT = (1, "待支付")
    PAID = (2, "已支付")
    CANCELLED = (3, "已取消")

class OrderEvent(BaseEvent):
    PAY = (1, "支付")
    CANCEL = (2, "取消")
```

**声明流转路由**：两张声明表——合法流转（仅做合法性校验，不强制目标一致）+ 事件处理器
（签名 `handler(current_state, params)`，同一事件可按当前状态分叉；持久化在此完成）：

```python
from web_infra import StateRouter, StateMachineRegistry, StateRouteParams

@StateMachineRegistry.register
class OrderStateRouter(StateRouter[OrderStatus, OrderEvent, OrderEO]):
    def get_state_event_target_config(self):
        return {
            OrderStatus.PENDING_PAYMENT: {OrderEvent.PAY: OrderStatus.PAID,
                                          OrderEvent.CANCEL: OrderStatus.CANCELLED},
        }

    def get_event_dispatcher(self):
        return {OrderEvent.PAY: self._pay, OrderEvent.CANCEL: self._cancel}

    def _pay(self, current_state, params):
        order = params.get_param("order")
        order.status = OrderStatus.PAID
        self.session.add(order)
        return OrderStatus.PAID
```

**触发流转**：非法流转 / 空状态 / 空参数抛 `E4-STATE-000~004` 业务异常：

```python
fsm = StateMachineRegistry.get(OrderStatus, OrderEvent, OrderEO)
new_status = fsm.fire(order.status, OrderEvent.PAY, StateRouteParams.create().add_param("order", order))
# 异步处理器：await fsm.fire_async(...)
```

**扩展/无限状态场景**：状态值不限于枚举。重试/累加类「无限状态」可用组合值表达，迁移表可程序化生成：

```python
class RetryRouter(StateRouter[tuple, str, OrderEO]):
    def get_state_event_target_config(self):
        return {(f"RETRYING_{n}"): {"RETRY": f"RETRYING_{n + 1}"} for n in range(3)}

    def get_event_dispatcher(self):
        return {"RETRY": lambda current_state, params: f"RETRYING_{int(current_state.split('_')[1]) + 1}"}
```

真正的「无界状态流/工作流」不属于本组件范畴，应使用工作流/任务编排引擎。

**引擎 SPI（可替换为第三方状态机库）**：`StateMachineEngine` 为引擎契约（`fire`/`fire_async`），
默认实现为自研 `StateMachine`。如需基于其他成熟状态机库（如 transitions）实现，可自定义引擎并注册替换
（须在 `get` 之前）：

```python
from web_infra import StateMachineEngine, StateMachineRegistry

class TransitionsEngine(StateMachineEngine[OrderStatus, OrderEvent]):
    def fire(self, current_state, event, params=None):
        ...  # 适配第三方库逻辑
    async def fire_async(self, current_state, event, params=None):
        ...  # 适配第三方库逻辑

StateMachineRegistry.register_engine_factory(OrderStatus, OrderEvent, OrderEO, TransitionsEngine)
```

**并发模型与线程安全**：引擎层无状态（`fire` 只读声明表、不修改共享状态），多线程/多协程并发调用安全；
`StateMachineRegistry` 为**进程内单例**，注册/获取的 check-then-act 由类级锁保护（并发首次 `get` 只构建一次、
并发注册仅一个成功），但**建议注册集中在启动期完成**、运行期只读 `get`。跨进程/多实例并发流转同一实体的
互斥由乐观锁或分布式锁负责（见下）。

**并发与事务约定**：引擎只计算状态、不写库。多实例并发触发同一实体流转（如支付成功 + 超时取消同时发生）
会状态错乱，**并发控制由调用方负责**：优先用数据库乐观锁（version 字段 CAS 更新，写入失败则本次流转失败重试），
或使用框架 `DistributedLock` 包住 fire。事务边界在路由处理器内用框架 `provide_db_session` 自行管理，引擎不介入。

**开箱即用**：启用/禁用互转无需声明，直接使用 `BaseStatus` / `StartStopEvent` / `BaseStatusRouter`
（状态翻转后自行落库）。

### 7.12 支付

支付模块（`web_infra/payment`）按《Web 系统通用架构规范 · 支付扩展 v1.0》实现渠道接入与资金兜底。

> **可选能力**：支付不随 `web_infra` 顶层导出（`import web_infra` 不加载支付模块、不注册支付错误码），需显式
> `from web_infra.payment import ...` 或经 `app.capabilities.enabled: [pay]` 主动引入；依赖链
> 支付 → 鉴权 → 认证 → 用户系统（业务实现），启用按包含关系自动带上前置，见 [docs/使用说明.md 4.2](./docs/使用说明.md#42-能力依赖与装配)。

**装配渠道（内存演示，注入骨架存储即获全套兜底）**：

```python
from web_infra.payment import (
    InMemoryPaymentFlowStore, InMemoryPaymentOrderStore,
    InMemoryPaymentGateway, PaymentGatewayRegistry,
)

gateway = InMemoryPaymentGateway(
    flow_store=InMemoryPaymentFlowStore(),   # 支付流水本地事务表（§5.2）
    order_store=InMemoryPaymentOrderStore(), # 本地支付订单（§4.2/§5.5）
)
PaymentGatewayRegistry.register("memory", gateway)  # 生产替换为 WeChatPayProvider 并注入 WechatPayConfig
```

**下单 / 回调校验（骨架自动完成：下单幂等 / 金额 / attach / 状态机 / 流水落库）**：

```python
from web_infra.payment import PaymentPrepayRequest, PaymentScene
from decimal import Decimal

resp = await gateway.prepay(PaymentPrepayRequest(
    scene=PaymentScene.APP, out_trade_no="T20260817001",
    description="测试订单", total_amount=Decimal("99.50"),
))
# 回调入口（渠道验签后）：await gateway.validate_callback(callback) 通过后再分发业务处理器
```

**对账 / 冲正 / 风控 / 审计（框架 SPI + 内存默认实现）**：

```python
from web_infra.payment import (
    ReconciliationService, InMemoryReconciliationAuditStore,
    PaymentRiskGuard, InMemoryLimitCounterStore, LimitRule,
)

service = ReconciliationService(flow_store, InMemoryReconciliationAuditStore(),
                                query_order=gateway.query_order)   # T+1 对账：差异分类 + 查单补记/冲正
guard = PaymentRiskGuard(InMemoryLimitCounterStore())             # 下单前风控：限额/频次/可疑拆分
await guard.check_prepay(user_id=1, channel="memory", amount=Decimal("99.50"),
                         rule=LimitRule(per_transaction=Decimal("5000")))
```

**能力速查**：渠道骨架（`PaymentChannelTemplate`）、状态机（`PaymentStateMachine`）、超时关单
（`close_expired_orders`）、冲正（`reversal_flow`）、账单文件（`BillFileManager`）、审计
（`PaymentAuditStore`）、权限点（`PaymentPermission`）、契约测试（`payment/testing`）。

**文档**：[订单兜底策略](./docs/订单兜底策略.md) / [SPI-Extensions §15](./docs/SPI-Extensions.md#15-支付模块payment)

## 8. 项目结构

数据库脚本（DDL/DML）按规范 §13.2 存放于项目根 `db/` 目录（与代码一同纳入版本控制）：基线脚本 `db/init/ddl|dml/`（命名 `序号-模块-init-ddl/dml.sql`，如 `001-mq-init-ddl.sql`），增量脚本 `db/versions/`（命名 `V{版本号}-模块-{变更描述}-ddl/dml.sql`）。

增量脚本（`db/versions/`）示例与规则（整改 S13-2）：

- 命名：`V{版本号}-{模块}-{变更描述}-ddl.sql` / `-dml.sql`，同一变更的 DDL 与 DML 必须同版本成对提供（`V0.2.0-mq-outbox-next-retry-ddl.sql` / `-dml.sql`）。
- 基线不可回改：`db/init/` 只随大版本基线重建；已发布的表结构变更一律通过新增版本脚本演进，禁止修改既有基线脚本。
- DDL/DML 配套：纯加列（nullable/带默认值）不改变存量语义时 DML 可为空，但需在脚本头声明"无数据迁移"；涉及存量数据语义变更（回填/清洗/转换）必须提供幂等的 DML（带 `WHERE` 过滤已完成处理的行）。
- 脚本头统一携带 `@Author / @Date / @Description`，与代码注释规范一致。

### 8.1 Alembic 数据库变更管理（整改 S13-1）

数据库结构变更以 **Alembic** 为权威变更管理工具（规范 §13.1：脚本纳入版本控制、有版本校验，保证多环境一致性），迁移脚本位于项目根 `alembic/versions/`（命名 `{序号}_{变更描述}.py`）。`db/init/` 与 `db/versions/` 手工 SQL 保留作为参考（非 Python 环境 / DBA 手工执行 / 快速建库），**新变更一律优先编写 Alembic 迁移**。

- **基线/增量对应关系**：迁移链 `0001_message_outbox`（基线，等价 `db/init/ddl/001-mq-init-ddl.sql`）→ `0002_add_next_retry_at`（等价 `db/versions/V0.2.0-mq-outbox-next-retry-ddl.sql` 语义：新增 `next_retry_at` 列 + `idx_status_next_retry` 索引）。`alembic upgrade head` 后的表结构与基线 SQL 文件当前形态等价。Alembic 迁移不承载数据回填，存量数据修正 DML 见 `db/versions/` 手工脚本（如 `V0.2.0-mq-outbox-next-retry-dml.sql`）。
- **数据库 URL**：由 `alembic/env.py` 注入，优先级 进程/容器环境变量 `DATABASE_URL` > 项目根 `.env`（`alembic/env.py` 复用框架 `load_env_file` 自动加载，迁移命令单独执行时同样生效，无需在 shell 预先导出）> `alembic.ini` 的 `sqlalchemy.url`（留空）。支持异步驱动（`mysql+aiomysql` / `sqlite+aiosqlite`，项目 MySQL 默认异步）与同步驱动（`mysql+pymysql` / `sqlite`）。
- **依赖**：Alembic 属运维工具，非运行时依赖，安装 `pip install -e ".[migrate]"`（optional `migrate` 组，见 `pyproject.toml`）。

```bash
# 升级到最新版本（cwd=项目根；未设置 DATABASE_URL 时使用 alembic.ini 配置）
alembic upgrade head
# 生成迁移（需业务模型已注册到 Base.metadata，接入点见 alembic/env.py 注释）
alembic revision --autogenerate -m "add_xxx_table"
# 查看迁移历史 / 当前版本 / 回滚一个版本
alembic history
alembic current
alembic downgrade -1
# 离线生成 SQL 脚本（不连库）
alembic upgrade head --sql
```

```
src/web_infra/
├── application.py      # 应用启动器（配置驱动装配 + /health /metrics）
├── result/             # 统一响应结构
├── error/              # 错误码 + 异常 + 全局异常处理
├── constants/          # 常量分类（Auth/Infra/Param/Sys/Biz + CacheKey + MQ）
├── config/             # YAML 配置读取（ConfigSource / Settings / Nacos 配置中心 / ConfigCipher 加密值）
├── capability/         # 能力注册表（能力契约 SPI + 依赖包含规则 + 装配校验：用户系统→认证→鉴权→支付）
├── context/            # 请求上下文（contextvars）
├── logging/            # 日志（统一格式 / TraceId / 脱敏）
├── resilience/         # 韧性设计（重试 / 熔断 / 限流 / 分布式锁）
├── cache/              # 缓存抽象 + 内存/Redis 实现 + KeyBuilder（租户维度）
├── db/                 # 数据库接口 + MySQL/MongoDB/Redis/SQLite + 多租户拦截
├── mq/                 # 消息队列抽象 + 幂等消费 + Outbox 本地事务表
├── storage/            # 对象存储抽象 + 分片上传（本地/MinIO）
├── payment/            # 支付 SPI（渠道抽象/回调验签/骨架兜底/对账/冲正/风控；可选能力，依赖 鉴权→认证→用户）
├── schedule/           # 定时任务调度（asyncio + 可选分布式锁）
├── registry/           # 服务注册发现 SPI（内存/Nacos）
├── loadbalance/        # 负载均衡 SPI（随机/轮询/平滑加权）
├── http/               # Feign 服务间调用客户端
├── security/           # JWT（kid 轮换 / refresh token）/ 密码 / 验证码 / 登录锁定 / RBAC / 数据权限 / OAuth2
├── task/               # 异步任务框架（状态机 / 心跳 / 死任务扫描）
├── monitoring/         # Prometheus 指标（连接池/运行时/线程池/缓存/存储/MQ/注册中心，懒注册按配置动态采集）+ AI 指标 + 阶段耗时 + HTML 可视化 + 自定义分组 SPI + SLO/错误预算 + 池使用率双条件预警
├── utils/              # 雪花 ID / 日期 / 文件锁 / Token 计数 / PDF 渲染
├── ai/                 # Provider SPI + 模型网关（配额/权限策略/流错误分片）+ Prompt + 检索 + 缓存 + 配额
│   ├── connection_pool/ # 连接池管理（流式/非流式分池）
│   └── concurrency/     # 单供应商并发控制（执行槽 + 有界排队）
└── web/                # FastAPI 集成（鉴权 / 幂等 / CORS / SSE / 健康检查）
```

## 9. 测试

单元测试使用 pytest + pytest-asyncio，位于 `tests/`，覆盖各能力模块：

```bash
# 运行全部测试
.venv\Scripts\python.exe -m pytest

# 运行指定模块测试
.venv\Scripts\python.exe -m pytest tests/test_model_auto_registrar.py -q

# 单元测试 + 覆盖率门禁（与 CI 一致，行覆盖率 <70% 失败，规范 §11.2）
.venv\Scripts\python.exe -m pytest --cov=web_infra --cov-fail-under=70

# 静态类型检查（pyright，含既有基线错误不阻塞新增）
.venv\Scripts\pyright.exe
```

质量门禁：**pytest 硬性通过 + 行覆盖率 ≥70%**（CI 失败即阻断，规范 §11.2）；pyright 现有基线错误不阻塞，但新增代码必须 0 错误。

## 10. Docker 镜像

项目提供基础镜像（`Dockerfile`，整改 S20-2 多阶段构建）：安装 `web_infra` 依赖（`min-monolith + migrate` extras，含 MySQL/SQLite ORM、Redis、Alembic）并默认启动 `create_app()`（含 `/health/live` `/health/ready` `/health` `/metrics`），业务项目 `FROM` 继承后挂载 `application.yml` 并覆盖启动命令。

构建与运行：

```bash
docker build -t flower-web-infrastructure:latest .
docker run -d -p 8000:8000 -v "$(pwd)/application.yml:/app/application.yml" flower-web-infrastructure:latest
# 健康检查（整改 S19-1 存活/就绪分离）：
# 存活探针 curl http://localhost:8000/health/live（进程存活，不探测依赖）
# 就绪探针 curl http://localhost:8000/health/ready（依赖连通性 + 启动完成）
```

> 镜像标签规范（整改 S20-3）：push `main` 推测试标签 `main-<时间戳>-<构建号>` 并更新 `latest`；版本 tag `v*` 推 SemVer + `latest`，详见 [CI/CD 文档](./docs/CI-CD.md)。

业务项目继承示例（`Dockerfile`）：

```dockerfile
FROM flower-web-infrastructure:latest

COPY app ./app          # 业务代码
COPY application.yml ./application.yml

# 基础镜像只拷贝 site-packages（无 uvicorn 控制台脚本），启动用 python -m uvicorn
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 11. CI/CD

GitHub Actions 工作流位于 `.github/workflows/ci.yml`，推送 `main` / `dev` / 版本 tag `v*` / 提交 PR 时自动执行：

- **test**：静态类型检查（pyright，容忍既有基线）+ 单元测试（pytest，硬性门禁）；
- **build-image**：Docker 基础镜像构建 + Trivy 漏洞扫描 + cosign keyless 签名（OIDC，无需密钥）+ `/health/live` 存活冒烟验证 + GHCR 推送（push `main` 推测试标签与 `latest`，版本 tag 推 SemVer + `latest`，dev push 与 PR 不推送）。

**触发规则**：

- **dev 分支推送即验证**：推送 `dev` 运行全量验证（test + 镜像构建/漏洞扫描/冒烟，不推送镜像），保证 **CI 通过后再提 PR**；
- **非代码变更不触发**：仅修改文档与非代码文件（`*.md`、`docs/**`、`LICENSE`、`.gitignore`、`.env.example`、`db/**`、`data/**`）时，push `main` / `dev` 与 PR 均不运行流水线（`paths-ignore`）；
- **版本 tag 无条件触发**：`v*` 版本 tag 不受 `paths-ignore` 影响，保证正式版镜像必发布；
- **镜像签名**：cosign keyless（OIDC）签名，先推送 GHCR 再签名（cosign 只能签名仓库中的镜像，本地 `:ci` 标签会被解析到 Docker Hub 导致 401），部署侧必须配套 `cosign verify` 校验后再拉取镜像。

详细说明（触发时机、门禁策略、镜像推送、本地复现）见 [CI/CD 文档](./docs/CI-CD.md)。

## 12. 相关文档

| 文档                                      | 说明                                                                                                       |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| [使用说明](./docs/使用说明.md)              | 业务项目接入指南：最小/全量/按需安装、快速开始、配置说明、能力与依赖对照表                                  |
| [CI/CD 文档](./docs/CI-CD.md)              | CI 流水线触发时机、门禁策略、镜像推送开启方式、本地复现                                                    |
| [SPI 扩展点文档](./docs/SPI-Extensions.md) | 框架预留的全部 SPI 扩展点：接口清单、方法契约、默认实现与扩展接入方式（自定义供应商/存储/缓存/消息队列等） |
| [常量与错误码](./docs/常量与错误码.md) | **框架常量与错误码的单一权威清单**：全部常量（含 HTTP 状态码 `HttpStatusConstant`）与错误码总览，业务新增/引用前先查阅本文档，防止冲突或重复定义 |

## 13. 版本与兼容性

- 遵循语义化版本（SemVer）：`MAJOR.MINOR.PATCH`。
  - `MAJOR`：不兼容的破坏性变更；
  - `MINOR`：向后兼容的新能力；
  - `PATCH`：向后兼容的缺陷修复。
- 当前版本：**v0.1.0**（与 `pyproject.toml` 保持同步）。
- 错误码 `E<大类>-<子类/域>-<3位编号>`、成功码 `S0000` 一经发布不可变更语义。

### 13.1 自动版本管理

框架通过 `prepare-commit-msg` 钩子在每次 `git commit` 时**自动递增版本号**并**全框架统一同步**（自动纳入本次提交，无需手动维护）：

- 权威来源：`pyproject.toml` 的 `version` 字段（版本递增的基准）；
- 同步位置：`src/web_infra/__init__.py`（`__version__`）、README 当前版本展示（徽章 / 项目信息表 / §13）、README 演示示例（规则示例表 / 开发分支示例 / 合入指南，以基础版本为基数整体重算）、docs 中的版本示例（CI-CD.md 镜像标签、使用说明.md 安装命令）；
- 不随版本同步：`db/versions/` 与 `alembic/` 的 `V0.2.0-*` 数据库迁移链历史（改则破坏迁移对应关系）、`requirements.lock`（pip freeze 生成物，重新生成即可）、业务版本号（模型版本 / Prompt 模板版本 / 任务乐观锁）。

版本递增规则：

| 提交前缀（conventional commits）          | 版本变化        | 示例                          |
| ----------------------------------------- | --------------- | ----------------------------- |
| `feat` / `feat(scope)`                    | 小版本 +1       | `0.1.0` → `0.2.0`             |
| `fix` / `refactor` / `perf` / `test` / `build` / `ci` / `style` | 补丁 +1 | `0.1.0` → `0.1.1` |
| 含 `BREAKING CHANGE:`（footer）或 `!:`（如 `feat!: xxx`） | 大版本 +1 | `0.1.0` → `1.0.0` |
| `docs` / `chore`（纯文档/杂物）           | 不变            | —                             |
| `Merge ...` / revert / squash（无前缀，无法解析） | 跳过，不变 | —                             |
| 其他无前缀提交                            | 按补丁 +1（建议使用规范前缀） | `0.1.0` → `0.1.1` |

分支规则：

- **开发分支（`dev` / `dev/*` / `dev-*` / `*-dev`）**：打测试版本号（PEP 440），基础版本不动、仅递增 dev 序号，如 `0.1.0` → `0.1.0.dev0` → `0.1.0.dev1`；合入 `main` 后正式提交剥离 `.devN` 并按上表递增生成正式版本（如 `0.1.0.dev5` + fix → `0.1.1`）。
- **正式分支（`main` 等）**：直接按上表递增正式版本号。
- 版本打 tag（`v*`，触发 CI 正式版镜像发布）仍需手动执行，钩子只更新版本号不打 tag。

安装钩子（`.git/hooks` 不入库，每个 clone 后执行一次）：

```bash
python scripts/install_hooks.py             # 安装（已有他人钩子先备份为 .bak）
python scripts/install_hooks.py --uninstall # 卸载（自动恢复备份）
```

> 注意：提交前缀映射依赖 `prepare-commit-msg` 钩子，使用 `git commit --no-verify` 时不会触发自动版本更新。

#### 13.1.1 dev → main 合入时如何正确生成正式版本

版本号由**本地钩子**（`.git/hooks/`，仅在本地 `git commit` 时运行）与 **release workflow**（PR 合入后自动执行，见 [release.yml](./.github/workflows/release.yml)）协同维护。dev→main 合入推荐走 PR：

**首选：dev→main 走 PR 合入（自动发版，无需手动操作）**

dev 分支开发（本地钩子自动打 `X.Y.Z.devN` 测试版本号）→ 推送远程 → 创建 dev→main PR（网页或 `gh pr create` 均可）→ 合并 PR（网页 Merge / `gh pr merge` 均可）→ [release workflow](./.github/workflows/release.yml) 自动完成发版：

- 剥离 `.devN` 并按 **PR 标题前缀**递增：`feat`→小版本、`fix` 等→补丁、`!` / `BREAKING CHANGE`→大版本、`docs`/`chore`→仅剥离正式化不递增；
- 同步更新 README / docs 版本引用；
- 经 **release/vX.Y.Z 临时分支创建 PR 自动合入 main**（PR 触发 CI，检查通过后自动合并），全程符合 main 分支保护；
- 仅更新版本号，不打 tag。

注意：**PR 标题必须带 conventional 前缀**，否则按补丁处理；release workflow 只在 `base=main` + `head=dev` 且合并成功时触发（release 分支自身的 PR 不会触发，避免循环）。

**备选：本地合并（不走 PR，由本地钩子发版）**

```bash
git checkout main
git pull origin main
git merge --squash dev          # 将 dev 全部改动合并到暂存区（不产生 merge commit）
git commit -m "feat: <本次合入的功能描述>"   # 本地钩子：剥离 .devN 后按前缀递增
git push origin main
```

- 合入前 dev 版本为 `0.1.0.dev5`，合入后 main 上 `feat` 提交 → 剥离 `.devN` 得 `0.1.0` → 小版本 +1 → **`0.2.0`**（正式版），README 徽章 / 当前版本 / docs 示例随提交自动同步；
- 如需保留分支历史可改用 `git merge dev`：merge 提交钩子自动跳过（不更新版本），需在 main 上再提交一次（如 `fix: 合入后的收尾修改`）生成正式版本；
- 若 main 与 dev 都改过 `pyproject.toml` 产生冲突，手动保留版本号较高的一方即可（如保留 dev 的 `0.1.0.dev5`）。

> 合入 main 生成正式版本号后，如需发布正式版镜像，手动打 tag 推送即可（`git tag v0.2.0 && git push origin v0.2.0`，CI 的 `v*` tag 会触发正式版镜像构建与签名）。

## 14. 许可证

MIT License。
