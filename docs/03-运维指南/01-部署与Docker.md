# 部署与 Docker

> 面向运维/部署工程师：单体与微服务两种形态的部署差异、框架基础镜像构建、docker-compose 编排、健康探针、优雅停机、注册 IP 注入、环境变量清单与多实例部署注意事项。

## 目录

- [1. 部署形态总览：单体 vs 微服务](#1-部署形态总览单体-vs-微服务)
- [2. 框架基础镜像构建](#2-框架基础镜像构建)
- [3. 业务镜像构建：两种方式](#3-业务镜像构建两种方式)
- [4. docker-compose 编排](#4-docker-compose-编排)
- [5. 健康探针配置](#5-健康探针配置)
- [6. 优雅停机](#6-优雅停机)
- [7. 注册 IP 显式注入](#7-注册-ip-显式注入)
- [8. 环境变量注入清单（APP_* 全量）](#8-环境变量注入清单app_全量)
- [9. 多实例部署注意事项](#9-多实例部署注意事项)

---

## 1. 部署形态总览：单体 vs 微服务

框架同时支持单体与微服务两种形态，差异由**安装 extras 与 `application.yml` 组件实现**决定，启动代码（`create_app()`）两种形态一致。

| 维度 | 单体（min-monolith） | 微服务（min-microservice） |
| ---- | ---- | ---- |
| 安装 extras | `flower-web-infrastructure[min-monolith]`（核心 + MySQL/SQLite + Redis + Alembic） | `flower-web-infrastructure[min-microservice,migrate]`（另含 Nacos/RocketMQ/MinIO SDK） |
| 外部依赖 | MySQL（或 SQLite）+ Redis（可选） | MySQL + Redis + Nacos + RocketMQ + MinIO（参考脚手架 docker-compose，见 [§4](#4-docker-compose-编排)） |
| 组件实现 | `storage.type: local`、`mq.type: memory`、`registry.type: memory` | `storage.type: minio`、`mq.type: rocketmq`、`registry.type: nacos`（注册中心**禁止内存实现**） |
| 数据库 | 单库 | 服务分库（如 `flower_user` / `flower_order`），见 [数据库变更管理](./04-数据库变更管理.md) |
| 镜像 | 基于框架基础镜像（`FROM flower-web-infrastructure:latest`） | 自包含多阶段构建（需 nacos/rocketmq/minio SDK，基础镜像不含） |
| 伸缩单位 | 单应用整体扩缩容 | 按服务独立扩缩容，多实例必然存在 |

> 微服务形态多实例是常态，部署前必读 [§9 多实例部署注意事项](#9-多实例部署注意事项)：雪花 ID `SNOWFLAKE_WORKER_ID` 唯一、定时任务/Outbox 分布式锁、注册 IP 显式注入。

## 2. 框架基础镜像构建

框架自带 `Dockerfile`（多阶段构建，安全基线：非 root + 清理构建期工具），产物可作为**单体业务镜像的基础**。

```dockerfile
# ---- build 阶段：安装依赖到系统 site-packages ----
FROM python:3.11-slim AS build

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && \
    pip install ".[min-monolith,migrate]" && \
    # 清理构建期工具（Trivy 高危/严重阻断修复）：仅构建需要、运行时不需要
    pip uninstall -y setuptools wheel pip && \
    rm -rf /usr/local/lib/python3.11/site-packages/pip \
           /usr/local/lib/python3.11/site-packages/pip-*.dist-info

# ---- runtime 阶段：仅拷贝构建产物，非 root 运行 ----
FROM python:3.11-slim

ENV TZ=Asia/Shanghai PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# 仅拷贝 site-packages + 源码副本（运行时 import 解析走 site-packages）
COPY --from=build /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY src ./src

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade --no-install-recommends -y \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/python3.11/site-packages/pip \
           /usr/local/lib/python3.11/site-packages/setuptools \
           /usr/local/lib/python3.11/site-packages/pkg_resources \
           /usr/local/lib/python3.11/site-packages/wheel \
           /usr/local/lib/python3.11/site-packages/*-*.dist-info \
    && useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
ENV APP_HOST=0.0.0.0 APP_PORT=8000

# 默认以框架默认配置启动（含 /health/live /health/ready /health /metrics 端点）
CMD ["python", "-c", "import os, uvicorn; from web_infra import create_app; uvicorn.run(create_app(), host=os.environ['APP_HOST'], port=int(os.environ['APP_PORT']), log_level='info')"]

# 容器存活健康检查（对应 /health/live，见 §5）
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).status == 200 else 1)"
```

要点：

- **build 阶段安装 `[min-monolith,migrate]` extras**：与框架默认配置 `app.db.type: mysql` 及单体业务运行需求一致；`migrate` 供 Alembic 迁移在容器内执行。
- **runtime 仅拷贝 site-packages + 源码**：不重复安装、不携带 pip/setuptools/wheel 等构建期工具（消除 Trivy 高危漏洞门禁失败）。
- **基础镜像版本锁定**：`python:3.11-slim` 为浮动 patch 标签，生产建议锁定具体 digest（`docker pull python:3.11-slim && docker image inspect python:3.11-slim --format '{{index .RepoDigests 0}}'`）。
- **CI 联动**：框架 CI 自动构建/扫描/签名并推送 GHCR（`ghcr.io/flower-star-dream/flower-web-infrastructure:<版本>`），部署侧拉取前必须 `cosign verify`，详见 [CI-CD.md](../CI-CD.md)。

## 3. 业务镜像构建：两种方式

### 3.1 单体：FROM 框架基础镜像（推荐）

```dockerfile
# flower-monomer-scaffolding 业务镜像（精简自单体脚手架 Dockerfile）
FROM flower-web-infrastructure:latest    # 构建前先拉取框架基础镜像并打本地标签

WORKDIR /app
COPY src ./src
COPY application.yml ./application.yml

ENV PYTHONPATH=/app/src TZ=Asia/Shanghai
EXPOSE 8000

# 用 python -m uvicorn 启动（基础镜像只拷贝 site-packages，运行时无控制台脚本）
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

构建前置（参考单体脚手架 CI）：

```bash
docker pull ghcr.io/flower-star-dream/flower-web-infrastructure:v1.0.0
docker tag ghcr.io/flower-star-dream/flower-web-infrastructure:v1.0.0 flower-web-infrastructure:latest
docker build -t flower-monomer-app:latest .
docker run -d -p 8000:8000 -v "$(pwd)/application.yml:/app/application.yml" flower-monomer-app:latest
```

### 3.2 微服务：自包含多阶段构建

微服务需要 nacos/rocketmq/minio SDK，框架基础镜像仅含 min-monolith extras，故各服务镜像**自包含构建**（参考微服务脚手架各服务 Dockerfile）：build 阶段以 `git+https` 安装 `flower-web-infrastructure[min-microservice,migrate]`（锁定正式版本 tag），runtime 仅拷贝 site-packages + 业务代码。

```dockerfile
FROM python:3.11-slim AS build
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
# pip 以 git+https 拉取框架源码需要 git
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip && \
    pip install "flower-web-infrastructure[min-microservice,migrate] @ git+https://github.com/flower-star-dream/flower-web-infrastructure.git@v1.0.0" && \
    pip uninstall -y setuptools wheel pip && \
    rm -rf /usr/local/lib/python3.11/site-packages/pip /usr/local/lib/python3.11/site-packages/pip-*.dist-info

FROM python:3.11-slim
ENV TZ=Asia/Shanghai PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=build /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY src ./src
COPY application.yml ./application.yml
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/python3.11/site-packages/pip \
           /usr/local/lib/python3.11/site-packages/pip-*.dist-info \
           /usr/local/lib/python3.11/site-packages/setuptools \
           /usr/local/lib/python3.11/site-packages/setuptools-*.dist-info \
    && useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser
ENV PYTHONPATH=/app/src
EXPOSE 8001
CMD ["python", "-m", "uvicorn", "user_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

构建命令（在服务目录执行，参考微服务脚手架 docs/使用说明.md）：

```bash
docker build -t flower-microservices-user-service:latest  -f services/user-service/Dockerfile  services/user-service
docker build -t flower-microservices-order-service:latest -f services/order-service/Dockerfile services/order-service
docker build -t flower-microservices-gateway:latest       -f services/gateway/Dockerfile       services/gateway

docker run -d -p 8001:8001 --env-file .env flower-microservices-user-service:latest
```

## 4. docker-compose 编排

微服务脚手架 `docker-compose.yml` 提供本地/测试环境一键拉起外部依赖（MySQL/Redis/Nacos/RocketMQ/MinIO）。生产环境不依赖本文件——外部服务由运维提供，应用经 `.env` 环境变量接入（[配置管理](./02-配置管理.md)）。要点提炼：

```yaml
services:
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: flower_user          # 仅建首个库；分库基线见下方 volumes
      TZ: Asia/Shanghai
    ports: ["3306:3306"]
    volumes:
      # db/init 基线 SQL（ddl/dml 子目录 + init-mysql.sh）在容器首次初始化时执行
      - ./db/init:/docker-entrypoint-initdb.d:ro
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-proot"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 10

  nacos:
    # 注册中心 standalone 单机；9848 为 gRPC 端口（nacos-sdk-python v2 必需）
    image: nacos/nacos-server:v2.3.2
    environment:
      MODE: standalone
      NACOS_AUTH_ENABLE: "false"
    ports: ["8848:8848", "9848:9848"]

  rocketmq-namesrv:
    image: apache/rocketmq:5.3.0
    command: sh mqnamesrv
    ports: ["9876:9876"]

  rocketmq-broker:
    image: apache/rocketmq:5.3.0
    command: sh mqbroker -n rocketmq-namesrv:9876 --enable-proxy
    depends_on: [rocketmq-namesrv]
    ports: ["10911:10911", "8081:8081"]

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports: ["9000:9000", "9001:9001"]
    volumes: [minio_data:/data]
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 10s
      timeout: 5s
      retries: 10

volumes:
  mysql_data:
  minio_data:
```

- 使用：`docker compose up -d` / `docker compose ps` / `docker compose down`。
- `db/init/init-mysql.sh` 在容器首次初始化时依次执行 `ddl/*.sql` 与 `dml/*.sql`（按文件名排序，脚本内自带 `USE <database>` 切换服务分库）。
- 应用侧配置与 compose 对齐（127.0.0.1 各端口，`root/root`），生产改由 `.env` 注入。

## 5. 健康探针配置

框架提供三端点（`/health/live`、`/health/ready`、`/health` 兼容入口），见 [监控与告警](./03-监控与告警.md) 与开发文档 [监控与指标](../02-开发者指南/21-监控与指标.md)。

| 端点 | 语义 | 编排层用途 |
| ---- | ---- | ---- |
| `/health/live` | 进程存活，**不探测依赖**（组件 DOWN 不影响判定），恒 200 | Docker `HEALTHCHECK` / K8s `livenessProbe` |
| `/health/ready` | 已装配组件连通性探测 + 启动完成，任一组件 DOWN 返回 503 | K8s `readinessProbe` |

K8s 部署示例（`/health/live` 与 `/health/ready` 分离配置）：

```yaml
containers:
  - name: order-service
    image: ghcr.io/your-org/order-service:v1.0.0
    ports: [{ containerPort: 8002 }]
    livenessProbe:              # 存活：进程活着就 200，组件 DOWN 不摘除
      httpGet: { path: /health/live, port: 8002 }
      initialDelaySeconds: 15
      periodSeconds: 30
      timeoutSeconds: 5
    readinessProbe:             # 就绪：依赖（MySQL/Redis/Nacos…）全通才收流
      httpGet: { path: /health/ready, port: 8002 }
      initialDelaySeconds: 20
      periodSeconds: 10
      timeoutSeconds: 5
    lifecycle:
      preStop:                  # 先摘流再等待窗口（配合 §6 优雅停机）
        exec:
          command: ["sh", "-c", "sleep 5"]
```

Docker 原生：`HEALTHCHECK` 已在框架基础镜像内置（探测 `/health/live`）；业务镜像继承后无需重复声明（`/health/ready` 由编排层配置，见 CI-CD.md §6）。

> `/health/ready` 就绪失败只影响收流，不影响存活判定——组件故障时容器保持运行，由监控告警介入，避免反复重启。

## 6. 优雅停机

框架在应用停机流程内置等待窗口（源码 `Application._shutdown`，规范 §19.2 摘流量→等待窗口→连接排空→优雅退出）：

1. **摘流量**：由部署层完成（K8s `preStop` 摘流 / 注册中心下线），`/health/ready` 随组件关闭自然返回 DOWN；
2. **等待窗口**：`sleep app.graceful_shutdown_wait_seconds`，存量请求继续排空；
3. **连接排空**：依次关闭各组件 `close/stop`（数据库连接池、Redis、MQ 等）。

配置项（默认 0 秒，保持旧行为）：

```yaml
app:
  graceful_shutdown_wait_seconds: 10   # 生产建议 ≥ 10s
```

生产建议：等待窗口 **≥10s**（覆盖存量长请求排空）；K8s 场景需保证 `terminationGracePeriodSeconds` > 等待窗口 + 关闭耗时，否则窗口未走完进程即被强杀。

## 7. 注册 IP 显式注入

服务注册到 Nacos 的对外 IP 由框架分级探测（`NacosRegistration._get_local_ip`），优先级从高到低：

1. 配置显式指定：`app.registry.nacos.register_ip`（`APP_REGISTRY_NACOS_REGISTER_IP` 环境变量优先于 yml，遵循"环境变量 > 配置文件"）；
2. 通用环境变量 `NACOS_REGISTER_IP`；
3. K8s 自动注入 `POD_IP`（集群内跨节点可达）；
4. Docker 宿主机 `HOST_IP`（运维注入）；
5. 容器默认网关 IP（bridge 网络下为宿主机地址）；
6. UDP 探测本机出网 IP（裸机）；
7. 回环地址（兜底）。

```yaml
# K8s：无需配置，POD_IP 自动注入
# Docker 宿主机部署：注入 HOST_IP
# 通用：
env:
  - name: POD_IP
    valueFrom: { fieldRef: { fieldPath: status.podIP } }
```

> 容器场景下 UDP 探测拿到的通常是容器内部 IP（如 172.17.0.x），注册中心与其他服务不在同一设备时**外部不可达**。生产容器环境必须显式注入（POD_IP / HOST_IP / NACOS_REGISTER_IP / APP_REGISTRY_NACOS_REGISTER_IP 任选其一），否则下游服务无法访问本实例（现象：Feign 调用超时，见 [排障指南](./05-排障指南.md)）。

## 8. 环境变量注入清单（APP_* 全量）

框架默认配置 `application.default.yml` 中敏感项与连接参数均以 `${APP_*:默认}` 占位符外置（完整清单见 [配置参考](../02-开发者指南/03-配置参考.md) 与 `application.default.yml`），下表为生产注入常用全量：

| 环境变量 | 默认 | 对应配置 | 说明 |
| ---- | ---- | ---- | ---- |
| `APP_ENV` | dev | `app.env` | 环境标识 dev/test/stage/prod；**prod 触发诊断端点 IP 白名单等生产行为** |
| `APP_NAME` | Web Application | `app.name` | 应用名（服务注册名/指标 service 标签） |
| `APP_LOGGING_FILE` | logs/app.log | `app.logging.file` | 文件日志路径 |
| `APP_DB_MYSQL_HOST` / `PORT` / `DATABASE` | 127.0.0.1 / 3306 / 空 | `app.db.mysql.*` | MySQL 连接（微服务分库用 `APP_DB_<SVC>_MYSQL_DATABASE`，如 `APP_DB_USER_MYSQL_DATABASE`） |
| `APP_DB_MYSQL_USERNAME` / `PASSWORD` | root / 空 | `app.db.mysql.*` | MySQL 账号密码 |
| `APP_CACHE_REDIS_HOST` / `PORT` / `DB` | localhost / 6379 / 0 | `app.cache.redis.*` | Redis 连接 |
| `APP_CACHE_REDIS_USERNAME` / `PASSWORD` | 空 | `app.cache.redis.*` | Redis 账号密码 |
| `APP_MONGO_USERNAME` / `PASSWORD` / `APP_MONGO_URL` / `APP_MONGO_DATABASE` | 空 / mongodb://localhost:27017 / app | `app.mongo.*` | MongoDB |
| `APP_STORAGE_MINIO_ENDPOINT` | localhost:9000 | `app.storage.minio.endpoint` | MinIO 地址 |
| `APP_STORAGE_MINIO_ACCESS_KEY` / `SECRET_KEY` | 空 | `app.storage.minio.*` | MinIO 访问密钥 |
| `APP_MQ_ROCKETMQ_NAMESERVER` | localhost:9876 | `app.mq.rocketmq.name_server` | RocketMQ NameServer |
| `APP_REGISTRY_NACOS_SERVER` | localhost:8848 | `app.registry.nacos.server_addresses` | Nacos 地址（支持逗号分隔多地址） |
| `APP_REGISTRY_NACOS_NAMESPACE` / `GROUP` | public / DEFAULT_GROUP | `app.registry.nacos.*` | Nacos 命名空间/分组 |
| `APP_REGISTRY_NACOS_USERNAME` / `PASSWORD` | nacos / 空 | `app.registry.nacos.*` | Nacos 认证（敏感，写 .env） |
| `APP_REGISTRY_NACOS_ACCESS_KEY` / `SECRET_KEY` | 空 | `app.registry.nacos.*` | 阿里云 AK/SK 认证 |
| `APP_REGISTRY_NACOS_REGISTER_IP` | 空 | `app.registry.nacos.register_ip` | 注册对外 IP（显式注入，见 §7） |
| `APP_SEARCH_ELASTICSEARCH_USERNAME` / `PASSWORD` / `HOSTS` | 空 / ["http://localhost:9200"] | `app.search.elasticsearch.*` | Elasticsearch |
| `APP_PAYMENT_WECHAT_APPID` / `MCHID` / `API_V3_KEY` 等 | 空 | `app.payment.wechat.*` | 微信支付商户参数 |

非 APP_* 框架变量：

| 环境变量 | 默认 | 用途 |
| ---- | ---- | ---- |
| `JWT_SECRET_KEY` | 必填（启用 auth 时） | JWT 签发密钥（`EnvJwtKeyProvider`） |
| `CONFIG_ENCRYPT_KEY` | 空 | `enc:` 加密配置值 Fernet 密钥（见 [配置管理](./02-配置管理.md) §4） |
| `SNOWFLAKE_WORKER_ID` | 0 | 雪花 ID worker_id（多实例必配唯一，见 §9） |
| `LOCAL_STORAGE_PRESIGN_SECRET` | local-presign-secret | 本地存储签名 URL HMAC 密钥（生产必须注入） |
| `DATABASE_URL` | 空 | Alembic 迁移数据库 URL（见 [数据库变更管理](./04-数据库变更管理.md)） |
| `LLM_API_KEY` | 空 | AI 模型 API Key（`env:LLM_API_KEY` 引用） |

> 容器注入方式：`docker run --env-file .env` / K8s `env` 或 `secretKeyRef`。`.env` 已由框架自动加载（不覆盖已存在的环境变量），但**进程/容器注入的变量优先于 .env**——生产以编排层注入为准。

## 9. 多实例部署注意事项

### 9.1 雪花 ID worker_id 唯一

框架 `SnowflakeUtil` 读取 `SNOWFLAKE_WORKER_ID`（默认 0）。**多实例部署必须为每个实例配置唯一 worker_id**，否则同一毫秒内不同实例可能生成重复 ID（启动时未配置仅告警，不阻断）。K8s 可结合 StatefulSet 序号注入（如 `SNOWFLAKE_WORKER_ID=0,1,2…`）。

### 9.2 定时任务 / Outbox 需分布式锁

- `TaskScheduler` 支持 `lock_factory`（分布式锁工厂，`(task_name) -> 异步上下文管理器`）：提供时多实例仅单实例执行；锁竞争超时跳过本轮而非失败（不累计连续失败、不误暂停）。
- Outbox 轮询投递/清理任务（`register_outbox_tasks` 注册 `message-outbox-publish` / `message-outbox-cleanup`）同样应挂分布式锁，避免多实例重复投递（消费侧有 `bizId+msgId` 幂等键兜底，见 [排障指南](./05-排障指南.md) §5）。

### 9.3 其他

- 幂等中间件 / JWT 登出 / 消息幂等存储多实例需切 Redis 共享存储（`store_type: redis` / `RedisJwtTokenStore` / `RedisMessageIdempotencyStore`），内存实现仅单实例有效。
- 注册 IP 显式注入（§7）；Nacos 多实例注册同名服务自动负载均衡。
- 实例缩容前先摘流（注册中心下线 / preStop），再走优雅停机（§6）。
