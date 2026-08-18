# 消息队列与 Outbox（RocketMQ / 内存 / 幂等消费 / 可靠投递）

> 统一消息抽象 + 双实现（内存 / RocketMQ）：分区键哈希保证分区内串行、延迟消息、异常分类重试、幂等消费（7 天保留、Redis 跨实例原子）与死信治理；Outbox 本地事务表实现「业务写库 + 发消息」的最终一致性可靠投递。

## 目录

- [1. 是什么](#1-是什么)
- [2. Message 模型与发布 / 消费抽象](#2-message-模型与发布--消费抽象)
- [3. RocketMQ 实现](#3-rocketmq-实现)
- [4. 内存实现（InMemoryMessageQueue）](#4-内存实现inmemorymessagequeue)
- [5. 幂等消费：IdempotentConsumer](#5-幂等消费idempotentconsumer)
- [6. 重试分类：RetryableError / NonRetryableError](#6-重试分类retryableerror--nonretryableerror)
- [7. Outbox 可靠投递全流程](#7-outbox-可靠投递全流程)
- [8. MqConfig 配置项](#8-mqconfig-配置项)
- [9. 完整示例：业务写库 + Outbox 同事务](#9-完整示例业务写库--outbox-同事务)
- [10. 常见坑](#10-常见坑)

## 1. 是什么

`web_infra.capabilities.mq`（源码见 `src/web_infra/capabilities/mq/`）围绕规范 §9（消息队列）提供：

| 组件 | 职责 |
| ---- | ---- |
| `Message` | 统一消息结构（message_id / topic / tag / code / body / trace_id / partition_key） |
| `MessagePublisherInterface` / `MessageConsumerInterface` | 发布（`publish` / `send_delay`）与消费（`subscribe` / `start` / `stop`）抽象 |
| `InMemoryMessageQueue` | 内存双实现（进程内 asyncio.Queue），单实例/测试 |
| `RocketMqPublisher` | RocketMQ 生产端（rocketmq-client-python），多实例/微服务 |
| `MessageQueueRegistry` | 按 `app.mq.type` 装配（内置 `memory` / `rocketmq`） |
| `MessageQueueSelector` | 业务分区键稳定哈希选分区（`HashMessageQueueSelector`） |
| `IdempotentConsumer` / 幂等存储 | 消费幂等（内存 / Redis SETNX 跨实例原子） |
| `RetryableConsumer` | 消费异常分类重试封装（指数退避，超限/不可重试进 DLQ） |
| Outbox 子包 | 本地事务表可靠投递（内存 / MySQL 双存储 + 发布器 + 清理器 + DLQ 消费 + 定时装配） |

**何时用**：异步解耦、事件驱动、最终一致性（Outbox）、延迟任务（延迟消息）；单机/测试用 memory，生产多实例用 rocketmq。

> 安装：RocketMQ 需 `pip install "flower-web-infrastructure[rocketmq]"`（延迟导入）；内存实现在核心依赖内开箱即用。

## 2. Message 模型与发布 / 消费抽象

```python
from web_infra.capabilities.mq import Message, generate_message_id

msg = Message(
    topic="web-order-topic",            # Topic（建议用常量，如 INFRA_MQ_TOPIC_ORDER）
    tag="pay",                          # Tag（与业务域对齐，规范 §5.8）
    code="S0000",                       # 错误码（异步链路传递，规范 §4.5.4）
    body={"biz_id": "order-1001", "amount": 100},   # 消息体（必须含 biz_id 供幂等去重）
    trace_id="",                        # 链路追踪标识（建议从 RequestContext 透传）
    partition_key="order-1001",         # 业务分区键（同一业务主键恒落同一分区，分区内串行）
)
msg.message_id == generate_message_id()   # 缺省自动生成 uuid4().hex
```

发布与消费抽象（接口事实）：

```python
class MessagePublisherInterface(Protocol):
    async def publish(self, message: Message) -> str: ...       # 发送，返回消息 ID
    async def send_delay(self, message: Message, delay_seconds: int) -> str: ...  # 延迟消息

class MessageConsumerInterface(Protocol):
    def subscribe(self, topic: str, handler: MessageHandler) -> None: ...   # MessageHandler = Callable[[Message], Awaitable[None]]
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
```

**分区语义（规范 §9.2）**：`partition_key` 为业务分区键，发布端按业务主键稳定哈希（`zlib.crc32` 取模）选分区，同一业务主键的消息恒落入同一分区，在分区内按序串行消费——保证同一订单的消息顺序性。无分区键则无分区要求。

## 3. RocketMQ 实现

`RocketMqPublisher` 基于 `rocketmq-client-python`（C++ 绑定，**Windows 安装较困难**，API 随版本略有差异；Linux/macOS 环境更顺）。

```yaml
app:
  mq:
    type: rocketmq
    rocketmq:
      name_server: localhost:9876
      group_name: web-producer-group
      send_timeout: 3000
```

```python
from web_infra.capabilities.mq import Message, RocketMqPublisher, RocketMqConfig

publisher = RocketMqPublisher(
    RocketMqConfig(name_server="localhost:9876", group_name="web-producer-group")
)

# 普通发送：带分区键保证分区内串行
await publisher.publish(Message(
    topic="web-order-topic", body={"biz_id": "order-1001"}, partition_key="order-1001",
))

# 延迟消息：映射 RocketMQ 官方固定 delay level（1s~2h 共 18 档），禁止业务 sleep
await publisher.send_delay(
    Message(topic="web-order-topic", body={"biz_id": "order-1002", "action": "timeout-close"}),
    delay_seconds=30,        # 向上取整映射到最近档位（30s → level 4）
)
```

**延迟等级映射**（源码 `_DELAY_LEVEL_SECONDS`，对齐 server.conf `messageDelayLevel`）：

| level | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 |
| ---- | - | - | - | - | - | - | - | - | - | -- | -- | -- | -- | -- | -- | -- | -- | -- |
| 时长 | 1s | 5s | 10s | 30s | 1m | 2m | 3m | 4m | 5m | 6m | 7m | 8m | 9m | 10m | 20m | 30m | 1h | 2h |

规则：按请求秒数取**最近不小于目标时长**的档位（宁高勿低）；超过 2 小时（7200s）抛 `ValueError`。发送时兼容新旧两版 SDK API（新版 `send_sync(msg, delay_level=level)`，旧版 `msg.set_delay_time_level(level)` 后 `send_sync(msg)`）。消息正文以 `json.dumps(body, ensure_ascii=False)` 序列化，`message_id` 写入 `set_keys`。发布走 `asyncio.to_thread` 不阻塞事件循环。

## 4. 内存实现（InMemoryMessageQueue）

`InMemoryMessageQueue` 同时实现发布与消费接口，基于 `asyncio.Queue`（单实例/测试场景，多实例必须换 RocketMQ，规范 S1-1）。**消费失败不静默丢弃（S9-1）**：

```python
from web_infra.capabilities.mq import InMemoryMessageQueue, Message, NonRetryableError

mq = InMemoryMessageQueue(
    dead_letter_topic="web-dlq-topic",   # 死信主题（P0-3/S9-7）
    max_retries=3,                       # 可重试失败最大重试次数（默认 3）
    retry_backoff_seconds=5,             # 指数退避基数：base * 2^retry_count（S9-4）
    partition_count=4,                   # 分区数（按业务分区键哈希选分区）
)

async def handler(message: Message) -> None:
    if message.body.get("amount", 0) < 0:
        raise NonRetryableError("业务校验失败")     # 不可重试 → 直接进死信
    # ... 业务处理；抛普通异常 → 指数退避重试，超限进死信

mq.subscribe("web-order-topic", handler)
await mq.start()

await mq.publish(Message(topic="web-order-topic", body={"biz_id": "b-1"}))
# 延迟消息 + 到期二次校验：
await mq.send_delay(Message(topic="web-order-topic", body={"biz_id": "b-2"}), delay_seconds=10)
# mq.cancel_delayed(message_id)   # 业务可在到期前取消（S9-3）

await mq.stop()
```

失败治理流程（源码事实）：

1. 可重试异常（普通异常 / `RetryableError`）：`retry_count + 1 ≤ max_retries` → `delay = retry_backoff_seconds × 2^(retry_count-1)` 后重新入队（仍按分区键选分区，保持分区内串行）；超限 → 投递死信。
2. 不可重试异常（`NonRetryableError`）：不重试，直接投递死信。
3. 死信消息包裹原始信息：`body = {original_msg_id, original_topic, biz_id, retry_count, error, payload}`，topic 为 `dead_letter_topic`。
4. 消费成功会清理该 `message_id` 的重试计数（防内存无限增长）。
5. 延迟消息到期做**二次校验**（`cancel_delayed` 标记的丢弃不投递，防止过期消息被消费）。

## 5. 幂等消费：IdempotentConsumer

所有消费者必须以 `bizId + msgId` 为幂等键、保留 **7 天**（规范 §9.2；区别于 API 幂等键 24h 重试窗口）。`IdempotentConsumer` 先占幂等键再执行业务，重复消费直接跳过视为 ACK：

```python
from web_infra.capabilities.mq import IdempotentConsumer, InMemoryMessageIdempotencyStore

consumer = IdempotentConsumer(
    InMemoryMessageIdempotencyStore(),   # 单实例；多实例换 RedisMessageIdempotencyStore
    retain_days=7,                       # 幂等键保留天数（默认 7 天）
    biz_id_field="biz_id",               # 消息体中的业务键字段名
)

async def consume(message: Message) -> None:
    processed = await consumer.consume(message, handler)   # True=首次执行业务；False=重复跳过
```

**去重语义**（源码 `_build_key`）：

- 消息体含 `biz_id`（且与 message_id 不同）→ 幂等键为 `biz:{biz}`：**业务级去重**——同一业务动作无论 msgId 均去重，覆盖 Broker 投递重试产生的不同 msgId；
- 消息体无 `biz_id` → 退化为 `msg:{message_id}`：**消息级去重**。
- **业务失败自动回滚幂等键**（`release`）：允许重试；只有业务成功才保留幂等键。

存储实现（`MessageIdempotencyStoreInterface`：`try_consume(key, ttl_seconds)` / `release(key)`）：

- `InMemoryMessageIdempotencyStore`：内存字典 + asyncio.Lock（单实例，惰性清理过期键）；
- `RedisMessageIdempotencyStore`：`SET key 1 NX EX ttl` **原子写入保证跨实例幂等**（多实例场景必须用），Key 经 `CacheKeyBuilder` 生成 `web:mq:v1:msg_idem:{topic}:{message_id}`（规范 §5.7 模板）。

```python
from web_infra.capabilities.mq import RedisMessageIdempotencyStore

redis_store = RedisMessageIdempotencyStore(await cache.config.connect())  # 复用 cache 组件 Redis 连接
consumer = IdempotentConsumer(redis_store)
```

## 6. 重试分类：RetryableError / NonRetryableError

消费异常分两类（`mq_exceptions.py`，规范 §9.1 / S9-1），供 `RetryableConsumer` 与内存队列消费统一分流：

```python
class RetryableError(Exception):      # 可重试：网络超时、Broker 抖动等临时故障
class NonRetryableError(Exception):   # 不可重试：业务校验失败、消息格式非法等（重试无意义）
```

`RetryableConsumer` 封装"重试 → 超限/不可重试进 DLQ"（可与 `IdempotentConsumer` 组合：业务失败回滚幂等键后可安全重试）：

```python
from web_infra.capabilities.mq import RetryableConsumer, RetryableError, NonRetryableError

consumer = RetryableConsumer(
    dlq_publisher=app.state.mq,      # 死信发布者（MessagePublisherInterface）
    max_retries=3,                   # 可重试最大重试次数（规范 §9.6）
    retry_backoff_seconds=5,         # 指数退避基数：base * 2^attempt（S9-4）
    dlq_topic="web-dlq-topic",       # 与 MqConfig.dead_letter_topic 对齐
)

async def safe_consume(message: Message) -> bool:
    return await consumer.consume(message, wrapped_handler)
    # True=业务成功；False=已进死信（不可重试或重试超限）
```

治理规则：`NonRetryableError` 立即进 DLQ 不重试；普通异常按 `max_retries` 上限指数退避重试（`delay = backoff × 2^attempt`），超限进 DLQ；死信消息同样包裹 `original_msg_id / original_topic / biz_id / retry_count / error / payload`；死信投递失败只留日志不阻塞调用方。

## 7. Outbox 可靠投递全流程

**解决什么问题**：业务先写库再发消息，若发消息失败会导致消息丢失（或先发消息再写库导致下游看到未落库的数据）。Outbox 把"发消息"变成一次**本地数据库事务**：业务数据 + Outbox 消息**同事务写入**，再由独立轮询任务投递到 MQ——本地事务提交成功则消息必在，投递失败可重试（规范 §21.3 / §9.8 最终一致性）。

**状态机**（`OutboxStatus`，入库存 code 禁存枚举名）：

```
PENDING(0 待发送) ──投递成功──▶ SENT(1 已发送) ──7 天后──▶ 清理
      │
      ├──重试超限（未投递死信）──▶ FAILED(2 失败超限)
      └──投递死信主题──▶ DLQ(3 死信) ──人工/自动 requeue──▶ 新 PENDING 记录
```

**存储接口** `OutboxStoreInterface`：`append` / `next_pending` / `mark_sent` / `mark_failed` / `mark_dlq` / `cleanup_sent`。双实现：

- `InMemoryOutboxStore`（默认，单实例）；
- `MysqlOutboxStore`（生产，表 `message_outbox`，DDL 见 `db/init/ddl/001-mq-init-ddl.sql`：`UNIQUE KEY uk_msg_biz(msg_id, biz_id)` + `KEY idx_status_next_retry(status, next_retry_at)`；**append 支持传入业务会话同事务写入**，其余方法内部自建会话并提交；SQL 为通用 ANSI 子集，测试可用 sqlite+aiosqlite 验证语义）。

```python
from web_infra.capabilities.mq import MysqlOutboxStore, OutboxPublisher, OutboxCleaner
from web_infra.capabilities.mq.outbox import register_outbox_tasks

# 1) 存储（生产）：复用数据库组件的会话工厂
store = MysqlOutboxStore(db.session_factory)      # MySQLDatabase.session_factory（async_sessionmaker）

# 2) 发布器（轮询投递：指数退避 + 重试超限进 DLQ）
publisher = OutboxPublisher(store, app.state.mq, config=MqConfig(
    max_retry=3, retry_backoff_seconds=30, dead_letter_topic="web-dlq-topic",
))
# 或 register_outbox_tasks(scheduler, store, app.state.mq, config=..., ...) 直接装配定时任务（见下）

# 3) 手动单轮投递
sent = await publisher.publish_pending()          # 返回投递成功条数

# 4) 清理已发送超过保留期的记录（默认 7 天）
cleaner = OutboxCleaner(store, retain_days=7)
removed = await cleaner.cleanup()
```

**指数退避与死信**（`OutboxPublisher._handle_failure`）：投递失败 `retry_count + 1`；未超限 → `mark_failed(msg_id, max_retries, retry_delay_seconds=base × 2^retry_count)` 设置 `next_retry_at`（`next_pending` 只取 `next_retry_at IS NULL OR <= now` 的记录，退避期不重复投递）；超限 → 先 `mark_failed(...)`（状态 FAILED）→ 投递死信主题（消息包裹 `original_msg_id / original_topic / biz_id / payload`）→ `mark_dlq`（状态 DLQ，回写 `dlq_at`）。

**死信治理与回放**（`dlq_consumer.py`）：`DlqConsumer` 订阅死信主题（默认记录日志 + 指标告警，不自动重放避免风暴）；`requeue_dlq_to_outbox(store, message)` 把死信消息**重投递回 Outbox**（新 `OutboxRecord`，状态重置 PENDING，topic 回落到原始业务主题，可再次轮询投递）：

```python
from web_infra.capabilities.mq import DlqConsumer, requeue_dlq_to_outbox

dlq_consumer = DlqConsumer(
    app.state.mq,                                  # 消息消费者
    dlq_topic="web-dlq-topic",
    on_dlq=lambda m: requeue_dlq_to_outbox(store, m),   # 治理钩子：自动回放（或自定义丢弃策略）
)
await dlq_consumer.start()
```

**定时装配**（`outbox_task_registrar.py`，S21-2）：`register_outbox_tasks` 把轮询投递与清理注册进 `TaskScheduler`，任务名 `message-outbox-publish` / `message-outbox-cleanup`（命名含模块归属）。**调度遵守 §23 防重复执行**（`TaskScheduler` 支持分布式锁，多实例部署时确保只有一个实例在投递，避免重复投递）：

```python
from web_infra.capabilities.schedule import TaskScheduler
from web_infra.capabilities.mq.outbox import register_outbox_tasks

scheduler = TaskScheduler(
    lock_factory=distributed_lock_factory,   # 多实例部署必须传分布式锁工厂（规范 §23.2 单实例执行）
)                                            # 单实例场景可不传（不取锁）
register_outbox_tasks(
    scheduler,
    store=store,                     # Outbox 存储（MysqlOutboxStore / InMemoryOutboxStore）
    publisher=app.state.mq,          # 消息发布者
    config=MqConfig(max_retry=3, retry_backoff_seconds=30, dead_letter_topic="web-dlq-topic"),
    publish_interval_seconds=5,      # 轮询投递间隔（秒）
    cleanup_interval_seconds=3600,   # 清理间隔（秒）
    batch_size=100,                  # 单轮投递条数上限
    retain_days=7,                   # 已发送记录保留天数（规范 §21.3）
)
scheduler.start()                    # 启动调度循环（同步方法；多实例传入 lock_factory 分布式锁）
await scheduler.stop()               # 应用停机时停止
# 返回任务名：["message-outbox-publish", "message-outbox-cleanup"]
```

> 默认不启用：`app.mq.outbox.enabled` 默认 `false`，框架不自动注册定时任务，由业务显式调用 `register_outbox_tasks` 装配（`enabled` 仅作业务配置参考）。

## 8. MqConfig 配置项

`application.default.yml` 中 `app.mq` 全量配置（`MqConfig` / `RocketMqConfig` 字段）：

| 配置项 | 默认值 | 说明 |
| ---- | ---- | ---- |
| `app.mq.type` | `memory` | `memory`（单实例）/ `rocketmq`（多实例）；自定义经 `MessageQueueRegistry.register` 接入 |
| `app.mq.rocketmq.name_server` | `localhost:9876` | RocketMQ NameServer 地址 |
| `app.mq.rocketmq.group_name` | `web-producer-group` | 生产者组名 |
| `app.mq.rocketmq.send_timeout` | `3000` | 发送超时（毫秒） |
| `app.mq.outbox.max_retry` | `3` | 投递失败最大重试次数（规范 §9.6） |
| `app.mq.outbox.retry_backoff_seconds` | `30` | 重试退避基数（秒），指数退避 `base × 2^retry_count`（S9-4） |
| `app.mq.outbox.dead_letter_topic` | `web-dlq-topic` | 死信主题（P0-3/S9-7） |
| `app.mq.outbox.publish_interval_seconds` | `5` | 轮询投递间隔（秒） |
| `app.mq.outbox.cleanup_interval_seconds` | `3600` | 清理间隔（秒） |
| `app.mq.outbox.retain_days` | `7` | 已发送记录保留天数（规范 §21.3） |
| `app.mq.outbox.enabled` | `false` | 仅供业务配置参考（默认不自动装配定时任务） |

> `MqConfig` 的三个字段（`max_retry` / `retry_backoff_seconds` / `dead_letter_topic`）与 `app.mq.outbox.*` 一一对应，是 `OutboxPublisher` / `RetryableConsumer` 的实际参数来源；`register_outbox_tasks` 传 `config=MqConfig(...)` 时这些字段生效。

## 9. 完整示例：业务写库 + Outbox 同事务

推荐写法（规范 §21.3 / S21-1）：**业务数据与 Outbox 消息在同一数据库事务中写入**，`append` 传入业务会话，业务提交则消息必在，业务回滚则消息一并回滚——不丢消息、不多发消息。

```python
from web_infra.capabilities.mq import OutboxRecord
from web_infra.capabilities.mq.outbox import MysqlOutboxStore

store = MysqlOutboxStore(db.session_factory)          # 应用启动时装配一次

async def create_order(order_no: str, amount: int) -> None:
    """下单：订单落库 + Outbox 消息同事务写入（生产环境，MySQL）"""
    async with db.orm_session() as session:           # 业务会话（框架管理生命周期）
        # 1) 业务数据写入（同一事务）
        session.add(Order(order_no=order_no, amount=amount))
        # 2) Outbox 消息同事务写入：session=业务会话，不独立提交
        await store.append(
            OutboxRecord(
                topic="web-order-topic",
                tag="created",
                biz_id=order_no,                       # 业务键（幂等键组成之一）
                payload={"order_no": order_no, "amount": amount},
            ),
            session=session,                           # 关键：与业务同事务
        )
    # 3) 退出 orm_session 上下文：业务数据 + Outbox 消息一并提交（异常一并回滚）

# 内存/测试场景：
async def create_order_memory() -> None:
    store = InMemoryOutboxStore()                      # 单实例默认实现
    record = await store.append(OutboxRecord(topic="web-order-topic", biz_id="o-1", payload={"a": 1}))
    # 轮询投递：await OutboxPublisher(store, publisher).publish_pending()
```

消费侧完整链路（幂等 + 重试 + DLQ 组合）：

```python
from web_infra.capabilities.mq import IdempotentConsumer, RetryableConsumer

idem = IdempotentConsumer(RedisMessageIdempotencyStore(redis_client))  # 多实例：Redis SETNX 原子
retry = RetryableConsumer(app.state.mq, dlq_topic="web-dlq-topic")

async def wrapped_handler(message: Message) -> None:
    await idem.consume(message, business_handler)      # 首次执行；重复消费跳过；业务失败回滚幂等键

async def on_message(message: Message) -> None:
    ok = await retry.consume(message, wrapped_handler) # 可重试指数退避，超限/不可重试进 DLQ
```

## 10. 常见坑

1. **`biz_id` 缺失导致去重退化**：消息体必须携带 `biz_id` 才能业务级去重；缺失时退化为消息级去重（`msg:{message_id}`），Broker 重投产生新 msgId 会重复执行业务。
2. **Windows 装不上 rocketmq-client-python**：C++ 绑定在 Windows 安装较困难（编译/依赖问题），开发可先用 `app.mq.type: memory`，生产部署到 Linux；延迟消息 API 新旧版本不一致，框架已兼容两种调用方式（见 §3）。
3. **延迟消息超过 2 小时**：RocketMQ 固定 delay level 最长 2h，超限抛 `ValueError`；更长延迟请用任务表/定时任务方案。
4. **内存队列消费异常被吞**：框架保证不静默丢弃（S9-1），但要求处理器**不要捕获全部异常后返回**——让异常向上抛，由 `InMemoryMessageQueue` / `RetryableConsumer` 统一做退避重试与 DLQ 治理。
5. **Outbox 投递被跳过**：`next_pending` 只取 `next_retry_at` 到期记录——失败后处于退避期，检查 `next_retry_at` 而非"以为丢了"；超限状态是 `FAILED`（未投递死信时）或 `DLQ`。
6. **多实例 Outbox 重复投递**：必须配分布式锁（`TaskScheduler` 内置）或仅单实例跑 `register_outbox_tasks`；同时投递同一 `msg_id` 依赖 `UNIQUE(msg_id, biz_id)` 约束兜底。
7. **append 忘传 `session`**：`MysqlOutboxStore.append` 不传 `session` 时自建会话独立提交——若业务事务随后回滚，Outbox 消息已提交造成"多发"；**同事务写入务必传 `session=业务会话`**。
8. **死信主题没人消费**：DLQ 是红线级治理位（P0-3/S9-7），必须有 `DlqConsumer` 订阅（记录/告警），并按需 `requeue_dlq_to_outbox` 回放或人工修复；放任不管会静默丢业务事件。
