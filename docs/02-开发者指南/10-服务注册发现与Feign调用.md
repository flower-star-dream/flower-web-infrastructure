# 服务注册发现与 Feign 调用

> 微服务之间怎么找到彼此、怎么调、挂了怎么兜底？框架把「注册中心」抽象成 SPI（内存 / Nacos 两套实现），
> 再配一个 Feign 风格声明式客户端（服务发现 + 负载均衡 + 重试 + 熔断降级），业务只写一行 `await client.get(...)`。
> 本文覆盖注册发现、三种负载均衡器、FeignClient 参数与兜底语义、服务注册引导全流程。

---

## 目录

- [1. 是什么](#1-是什么)
- [2. 注册中心实现](#2-注册中心实现)
- [3. 负载均衡器](#3-负载均衡器)
- [4. FeignClient](#4-feignclient)
- [5. build_feign_client 配置驱动装配](#5-build_feign_client-配置驱动装配)
- [6. 服务注册引导（startup 注册 / shutdown 注销）](#6-服务注册引导startup-注册--shutdown-注销)
- [7. 完整流程示例](#7-完整流程示例)
- [8. 配置项一览](#8-配置项一览)
- [9. 常见坑](#9-常见坑)

---

## 1. 是什么

### 1.1 ServiceInstance 模型

注册中心里的一条实例记录（对应 Spring Cloud ServiceInstance 概念，屏蔽具体注册中心差异）：

```python
from dataclasses import dataclass, field

@dataclass
class ServiceInstance:
    ip: str
    port: int
    weight: float = 1.0        # 权重（SWRR 负载均衡使用）
    metadata: dict = field(default_factory=dict)
    healthy: bool = True

    @property
    def host(self) -> str: ...    # "ip:port"
    @property
    def url(self) -> str: ...     # "http://ip:port"
```

### 1.2 ServiceRegistryInterface（SPI）

```python
class ServiceRegistryInterface(Protocol):
    async def register(self, service_name: str, instance: ServiceInstance) -> bool: ...
    async def deregister(self, service_name: str, instance: ServiceInstance) -> bool: ...
    async def get_instances(self, service_name: str) -> list[ServiceInstance]: ...  # 仅健康实例
    async def close(self) -> None: ...
```

业务代码只依赖这个接口（`FeignClient` 也只依赖它），注册中心可整体替换（Nacos / Eureka / Consul / 内存）。

---

## 2. 注册中心实现

框架内置 `memory` / `nacos` 两种后端，由 `create_app` 按 `app.registry.type` 经 `ServiceDiscoveryRegistry` 装配，组件挂到 `app.state.registry`。

### 2.1 内存实现（InMemoryServiceRegistry，单机/测试）

- 进程内字典 + `asyncio.Lock`（仅单事件循环，@Stateful 单实例）；
- **过期淘汰**：`instance_expire_seconds`（默认 15 秒）内未刷新的实例视为过期，`get_instances` 时惰性剔除（按 `time.monotonic()` 时间戳判定，每次发现顺带清理）；
- 提供 `update_metrics()` 供 `/metrics` 抓取各服务在线实例数。

```python
from web_infra import InMemoryServiceRegistry, ServiceInstance

reg = InMemoryServiceRegistry(instance_expire_seconds=15)
await reg.register("user-service", ServiceInstance(ip="127.0.0.1", port=8001, weight=1.0))
instances = await reg.get_instances("user-service")   # [ServiceInstance(ip=..., port=8001)]
```

### 2.2 Nacos 实现（NacosDiscoveryClient，生产）

基于**官方 `nacos-sdk-python` v2（gRPC 协议）**实现 `ServiceRegistryInterface`：

- `NacosNamingService` 延迟创建（首次调用建立 gRPC 连接）并复用；
- 注册为**临时实例**（`ephemeral=True`），心跳由 SDK 自动保活，无需手动发心跳；配置 `heartbeat_interval`（默认 5 秒，映射 SDK 毫秒）；
- 发现走 `list_instances(healthy_only=True, subscribe=True)`（订阅模式，本地缓存）；
- 注册/注销/发现失败统一 `logger.warning` 并返回 `False` / `[]`，不向上抛（发现失败降级为空列表，由 FeignClient 侧走兜底）；
- `close()` 关闭命名服务连接释放 gRPC 资源。

### 2.3 注册 IP 探测（_get_local_ip 分级）

`NacosRegistration` 封装注册/注销并自动探测对外 IP，优先级从高到低（源码事实，见 `nacos_registration.py`）：

```
1. 配置显式指定  app.registry.nacos.register_ip（最高）
2. 环境变量      NACOS_REGISTER_IP
3. 环境变量      POD_IP          （K8s 自动注入，集群内跨节点可达）
4. 环境变量      HOST_IP         （Docker 宿主机 IP，运维注入）
5. 默认网关 IP   /proc/net/route （容器 bridge 网络下为宿主机地址，Linux 平台）
6. UDP 探测      连公共地址取本机出网 IP（裸机场景）
7. 回环地址      127.0.0.1（兜底）
```

> **容器生产必须显式注入**：UDP 探测在容器里拿到的通常是容器内部 IP（如 172.17.0.x），注册中心/其他服务不在同一设备时外部不可达。
> K8s 注入 `POD_IP`、Docker 注入 `HOST_IP`，或直接在 yml 配 `app.registry.nacos.register_ip` 最稳妥。
> 注意 `_get_default_gateway` 读 `/proc/net/route`，Windows 平台返回 None（自动落到 UDP 探测/回环）。

```python
from web_infra.capabilities.registry import NacosRegistration
from web_infra.capabilities.config.nacos_properties import NacosProperties

reg = NacosRegistration(NacosProperties(register_ip="10.0.0.5"))   # 显式指定对外 IP
ok = await reg.register("order-service", port=8002)                # ip 缺省自动探测
await reg.deregister()
```

---

## 3. 负载均衡器

`LoadBalancerInterface` 只有一个方法：`choose(instances: list[ServiceInstance]) -> ServiceInstance`（空列表抛 `ValueError`）。内置三种：

| 实现 | 策略 | 说明 |
| ---- | ---- | ---- |
| `RoundRobinBalancer` | 轮询 | `itertools.count()` 取模，**FeignClient 默认** |
| `RandomBalancer` | 随机 | `random.choice` |
| `WeightedRoundRobinBalancer` | 平滑加权轮询（SWRR） | nginx 同款算法：当前权重 += 配置权重 → 选最大 → 选中者 -= 总权重；**权重非正实例不参与调度**；实例集合/权重变化自动重置状态（带 `threading.Lock` 防并发漂移） |

```python
from web_infra import RoundRobinBalancer, RandomBalancer, WeightedRoundRobinBalancer, ServiceInstance

instances = [
    ServiceInstance(ip="10.0.0.1", port=8001, weight=5),
    ServiceInstance(ip="10.0.0.2", port=8001, weight=1),
]
balancer = WeightedRoundRobinBalancer()
for _ in range(6):
    print(balancer.choose(instances).host)   # SWRR：5:1 比例平滑分配，高权重不连续命中
```

---

## 4. FeignClient

### 4.1 构造参数与默认值（源码事实）

| 参数 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `registry` | 必传 | 服务注册发现 SPI |
| `load_balancer` | `RoundRobinBalancer()` | 默认轮询 |
| `timeout` | `30.0` 秒 | HTTP 请求超时（`INFRA_HTTP_TIMEOUT_SECONDS`） |
| `retries` | `3` | **最大尝试次数 = 1 次首次 + 2 次重试**（`INFRA_CALL_MAX_RETRIES + 1`），注意不是"额外重试次数" |
| `retry_delay_base` | `0.5` 秒 | 指数退避基数 |
| `retry_delay_max` | `8.0` 秒 | 退避上限 |
| `max_connections` | `100` | 连接池上限 |
| `max_keepalive_connections` | `20` | 连接池保活上限 |
| `circuit_breaker_config` | `None` | **None = 不启用熔断**；传入 `CircuitBreakerConfig` 才开启 |
| `fallback` | `default_service_fallback` | 降级回调 `fallback(service_name)`，仅熔断开启时生效 |
| `url_validator` | `None` | SSRF 防护钩子（默认不启用） |

重试退避公式（含抖动防惊群）：`delay = min(base * 2^attempt * jitter, max)`，`jitter ∈ [0.7, 1.0]`。

**可重试错误**：`httpx.TimeoutException` / `httpx.ConnectError` / HTTP 5xx / 429；其余异常（4xx 业务错误等）不重试。重试耗尽统一抛 `SYS_INTERNAL`（E5-SYS-001 域）「服务 {name} 调用失败」。

### 4.2 熔断与默认兜底

- **按服务维度熔断**：`_breakers: dict[service_name, CircuitBreaker]` 按目标服务懒创建（双重检查锁定防并发首请求计数分裂），每个服务独立统计与隔离；
- **默认兜底 `default_service_fallback`**：启用熔断且未显式传 `fallback` 时，熔断 OPEN 走统一降级响应——**HTTP 503 + `code=E5-SYS-002`（SYS_UNAVAILABLE）+ 「服务 {name} 暂不可用」**，业务无需重复实现兜底（详见 [订单兜底策略.md](../订单兜底策略.md) §3.2）；
- 业务自定义降级（如返回缓存数据）：构造时传 `fallback=my_fallback` 覆盖；
- `request` 方法：未启用熔断时直接走重试逻辑；启用时经 `CircuitBreaker.execute_async` 包裹，OPEN/异常走降级。

熔断参数（`CircuitBreakerConfig`，dataclass 冻结）：错误率阈值 50%、慢调用比例阈值 80%（慢调用判定 >1s）、OPEN 等待 30s、HALF_OPEN 试探 5 次、最小样本 10、滑动窗口 20。

### 4.3 链路头注入与凭证剥离

`_build_service_headers`（规范 §6.4）发起请求前：

1. **剥离**调用方透传的 `Authorization`（服务间调用禁止裸传用户凭证）；
2. 从 `RequestContext.snapshot()` 注入链路头：`X-Service-Id` / `X-User-Id` / `X-Trace-Id` / `X-Client-Id` / `X-Tenant-Id` / `X-Scope`（上下文无值跳过，不抛错）。

配合网关/入口中间件透传，整条链路可追踪。

### 4.4 404→None / 204→{} 是脚手架约定，不是框架内置（务必注意）

- `FeignClient.request` **原样返回 `httpx.Response`**（熔断降级时可能是 fallback 响应，业务 fallback 返回 None 时为 None），**框架不做任何状态码语义转换**；
- 脚手架演示服务 order-service 的 `UserClient.get_user`（`services/order-service/src/order_service/client/user_client.py`）封装了业务响应解释约定：
  - `404` → 返回 `None`（用户不存在）；
  - `>= 500`（含框架兜底 503）→ 统一抛 `SYS_UNAVAILABLE`（E5-SYS-002）；
  - 其余 → 取统一响应 `Result` 的 `data` 字段。
- 「204 → {}」约定在当前脚手架代码中**未见实现**（待确认），框架更未内置；业务若需要空响应归一化请自行在客户端封装。

### 4.5 SSRF 防护（可选）

`url_validator` 钩子：每次请求前对目标 URL 校验，抛 `ValueError` 即拒绝请求。框架提供示例 `default_url_validator`（拒绝 localhost/回环/内网/保留网段），**默认不启用**（缺省 None），由业务结合自身网络拓扑显式注入更强校验器，避免破坏既有内网服务调用。

---

## 5. build_feign_client 配置驱动装配

消除业务侧装配参数散落：`FeignClientConfig`（pydantic）收敛构造参数（默认值引用 InfraConstant），`build_feign_client` 从配置源读取 `app.feign.*` 段装配，熔断参数收敛于 `app.feign.circuit_breaker.*`（缺失则该段不启用熔断）。

```python
from web_infra import build_feign_client

# application.yml 声明 app.feign 段后，一行装配（registry 来自 app.state.registry）
feign = build_feign_client(registry=app.state.registry)
```

配置示例（业务项目 `application.yml`）：

```yaml
app:
  feign:
    timeout: 30                 # 请求超时（秒）
    retries: 3                  # 最大尝试次数（首次 + 重试）
    retry_delay_base: 0.5       # 退避基数（秒）
    retry_delay_max: 8.0        # 退避上限（秒）
    max_connections: 100        # 连接池上限
    max_keepalive_connections: 20
    circuit_breaker:            # 缺失/空段 = 不启用熔断
      failure_rate_threshold: 0.5
      slow_call_rate_threshold: 0.8
      slow_call_duration_threshold: 1.0
      wait_duration_in_open_state: 30.0
      permitted_calls_in_half_open_state: 5
      minimum_number_of_calls: 10
      window_size: 20
```

> `app.feign` 段**不在框架默认配置**（`application.default.yml`）中，业务按需声明；缺省时全部回落 InfraConstant 默认值。
> `fallback` / `url_validator` 是函数入参（yml 无法表达函数），由业务在调用 `build_feign_client` 时显式传入。

---

## 6. 服务注册引导（startup 注册 / shutdown 注销）

脚手架统一引导模式（`services/order-service/src/order_service/bootstrap.py` 为真实示例）：

```python
from web_infra import ServiceInstance
from web_infra.capabilities.registry import NacosRegistration

async def register_service(app, service_name: str, port: int) -> None:
    """应用启动时注册本服务实例到注册中心（app.state.registry 为 create_app 装配的组件）"""
    registry = getattr(app.state, "registry", None)
    if registry is None:
        return
    instance = ServiceInstance(ip=resolve_register_ip(), port=port)   # resolve_register_ip 复用框架分级探测
    ok = await registry.register(service_name, instance)
    app.state.service_name = service_name
    app.state.service_instance = instance

async def deregister_service(app) -> None:
    """应用停机时注销服务实例（幂等：未注册过则跳过）"""
    registry = getattr(app.state, "registry", None)
    service_name = getattr(app.state, "service_name", None)
    instance = getattr(app.state, "service_instance", None)
    if registry is None or service_name is None or instance is None:
        return
    await registry.deregister(service_name, instance)

# FastAPI 生命周期挂接（与脚手架 register_service/deregister_service 一致）
async def _startup() -> None:
    await register_service(app, "order-service", 8002)

async def _shutdown() -> None:
    await deregister_service(app)

app.router.add_event_handler("startup", _startup)
app.router.add_event_handler("shutdown", _shutdown)
```

---

## 7. 完整流程示例

注册发现 + Feign 调用（最小可运行，内存注册中心单机演示）：

```python
import asyncio
from web_infra import InMemoryServiceRegistry, ServiceInstance, build_feign_client

async def main():
    # 1. 注册中心：内存实现，注册两个 provider 实例
    registry = InMemoryServiceRegistry()
    await registry.register("provider-svc", ServiceInstance(ip="127.0.0.1", port=9001, weight=3))
    await registry.register("provider-svc", ServiceInstance(ip="127.0.0.1", port=9002, weight=1))

    # 2. FeignClient：默认轮询负载均衡 + 默认重试/超时（配置驱动可用 build_feign_client）
    feign = build_feign_client(registry=registry)   # 读取 app.feign 段（此处缺省回落默认值）

    # 3. 调用：自动发现实例 -> 负载均衡 -> 注入链路头（剥离 Authorization）-> 重试兜底
    resp = await feign.get("provider-svc", "/v1/status")
    if resp is not None and resp.status_code == 200:
        print(resp.json())

    # 4. 停机清理
    await feign.close()
    await registry.close()

asyncio.run(main())
```

业务侧封装（对齐脚手架约定，服务间调用统一异常语义）：

```python
from web_infra import CommonErrorCode

async def get_user_detail(feign, user_id: int) -> dict | None:
    resp = await feign.get("user-service", f"/v1/users/{user_id}")
    if resp is None:                                   # 业务 fallback 返回 None 时
        raise CommonErrorCode.SYS_UNAVAILABLE.to_exception(message="用户服务暂不可用（已降级兜底）")
    if resp.status_code == 404:
        return None                                    # 用户不存在（脚手架约定，非框架内置）
    if resp.status_code >= 500:                        # 上游 5xx / 熔断兜底 503
        raise CommonErrorCode.SYS_UNAVAILABLE.to_exception(message="用户服务暂不可用")
    return resp.json().get("data")
```

---

## 8. 配置项一览

| 配置项 | 默认值 | 说明 |
| ------ | ------ | ---- |
| `app.registry.type` | `memory` | memory / nacos / 自定义注册名（未注册抛 ConfigError） |
| `app.registry.expire_seconds` | `15` | 内存实现实例过期淘汰秒数 |
| `app.registry.nacos.server_addresses` | `localhost:8848` | Nacos 地址（逗号分隔多地址） |
| `app.registry.nacos.namespace` | `public` | 命名空间 |
| `app.registry.nacos.group` | `DEFAULT_GROUP` | 分组 |
| `app.registry.nacos.cluster` | `DEFAULT` | 集群 |
| `app.registry.nacos.username` / `password` | `${APP_REGISTRY_NACOS_USERNAME:nacos}` 等 | Nacos 认证（敏感项走 .env） |
| `app.registry.nacos.access_key` / `secret_key` | `${APP_REGISTRY_NACOS_ACCESS_KEY:}` 等 | 阿里云 AK/SK 认证（可选） |
| `app.registry.nacos.log_level` | `INFO` | SDK 日志级别 |
| `app.registry.nacos.grpc_timeout_ms` | `5000` | gRPC 请求超时（毫秒） |
| `app.registry.nacos.tls_enabled` / `tls_ca_file` / `tls_cert_file` / `tls_key_file` | `false` / 空 | TLS 配置 |
| `app.registry.nacos.heartbeat_interval` | `5` | 心跳间隔（秒，临时实例 SDK 自动心跳） |
| `app.registry.nacos.register_ip` | 空 | 注册对外 IP（生产容器显式注入；探测链 register_ip > NACOS_REGISTER_IP > POD_IP > HOST_IP > 网关 > UDP > 回环） |
| `app.feign.*` | 见 §5 | Feign 客户端装配参数（业务声明，框架无默认段） |
| 环境变量 `NACOS_REGISTER_IP` / `POD_IP` / `HOST_IP` | — | 注册 IP 探测的环境变量来源 |

---

## 9. 常见坑

1. **`retries=3` 是尝试总次数不是重试次数**：1 次首次 + 2 次重试；要"重试 3 次"需配 `retries: 4`。
2. **熔断默认关闭**：`circuit_breaker_config` 为 None 时不熔断；`app.feign.circuit_breaker` 空段/缺失同样不启用。兜底 `default_service_fallback` 只在**熔断开启**时生效——不开熔断时重试耗尽抛 `SYS_INTERNAL` 异常。
3. **容器 IP 探测坑**：不显式注入 `register_ip`/`POD_IP`/`HOST_IP` 时，容器内 UDP 探测拿到的是内部 IP，服务间调用会连不上；Windows 平台网关探测（/proc/net/route）自动跳过。
4. **404→None / 204→{} 不是框架语义**：FeignClient 原样返回响应；脚手架 UserClient 的 404→None 是业务封装约定，204→{} 当前未实现（待确认），不要在文档/交接中把二者当作框架能力。
5. **服务间调用禁止裸传用户凭证**：`Authorization` 会被自动剥离，改用 `X-Service-Id` 等服务身份头；跨服务身份传播依赖框架中间件/网关注入的上下文。
6. **内存注册中心多实例无效**：`InMemoryServiceRegistry` 是进程内状态，多实例部署必须 `app.registry.type: nacos`。
7. **SSRF 防护默认关闭**：需要防 SSRF 的业务显式传 `url_validator=default_url_validator` 或更强校验器。
8. **熔断计数按服务维度隔离**：一个服务熔断不影响其他服务；`_breaker_lock` 保证并发首请求只创建一个熔断器。
