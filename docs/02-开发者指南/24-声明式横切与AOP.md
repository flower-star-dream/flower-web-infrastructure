# 声明式横切与 AOP（切点 / 通知 / 切面 / 事务 / 缓存）

> 对标 Spring AOP 的声明式横切能力：用「切点匹配 + 通知 + 切面 + 装饰器织入」把事务、缓存、日志、审计等横切关注点从业务代码中剥离。框架已内置 `@transactional`（声明式事务）与 `@cacheable` / `@cache_evict`（声明式缓存），业务也可自定义切面。

---

## 目录

- [1. 是什么](#1-是什么)
- [2. 切点：Pointcut](#2-切点pointcut)
- [3. 通知：Advice / AdviceType](#3-通知advice--advicetype)
- [4. 切面：Aspect](#4-切面aspect)
- [5. 切面注册与顺序语义（重点）](#5-切面注册与顺序语义重点)
- [6. 织入：AspectWeaver / @aspect](#6-织入aspectweaver--aspect)
- [7. 组件访问器：get_component / all_components](#7-组件访问器get_component--all_components)
- [8. 声明式事务：@transactional](#8-声明式事务transactional)
- [9. 声明式缓存：@cacheable / @cache_evict](#9-声明式缓存cacheable--cache_evict)
- [10. 书写顺序约定](#10-书写顺序约定)
- [11. 最小可运行示例](#11-最小可运行示例)
- [12. 常见坑](#12-常见坑)

## 1. 是什么

`web_infra.core.aop`（源码见 `src/web_infra/core/aop/`）+ 两个内置横切器（`capabilities/db/transactional.py`、`capabilities/cache/cacheable.py`）共同提供横切能力：

| 组件                                                         | 职责                                                                                        |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| `Pointcut`                                                 | 切点匹配规则（对标 Spring PointcutExpression）：按 module/class/method/参数类型匹配目标方法 |
| `AdviceType` / `Advice`                                  | 通知类型（BEFORE/AFTER/AFTER_RETURNING/AFTER_THROWING/AROUND）与通知载体                    |
| `Aspect`                                                   | 切面 = 一个切点 + 一组通知（对标 Spring`@Aspect`）                                        |
| `AspectRegistry`                                           | 类级切面注册表（全局装配），按`(order, 注册序)` 排序命中切面                              |
| `AspectWeaver` / `aspect`                                | 装饰器织入器：按命中切面链嵌套包装目标函数                                                  |
| `bind_components` / `get_component` / `all_components` | 组件访问器：Advice 运行时按名取已装配组件（db/cache 等）                                    |
| `transactional`                                            | 声明式事务（装饰器直接织入，不依赖切面匹配）                                                |
| `cacheable` / `cache_evict`                              | 声明式缓存（普通装饰器形态，不参与切面 order）                                              |

**与 Spring 的关键差异**：Spring 以 AOP 代理织入，本框架以 **Python 装饰器**织入（`aspect` 装饰器触发 `AspectWeaver.weave`）。`@transactional` 与 `@cacheable` 均为独立装饰器，不依赖全局切点匹配（见 §8 / §9）。

## 2. 切点：Pointcut

```python
from web_infra import Pointcut

pointcut = Pointcut(
    module=None,          # 模块名正则（如 r"service\.order"；None 不限制）
    class_=None,          # 类名正则（如 "OrderService"；None 不限制）
    method=None,          # 方法名正则（如 "create_.*"；None 不限制）
    arg_types=(),         # 第一个参数的类型名元组（如 ("_Model",)；空元组不限制）
)

pointcut.matches("service.order.OrderService.create_order")   # 是否命中（拆解 target 匹配）
pointcut.matches_method("create_order")                        # 仅方法名匹配
pointcut.matches_args((order_model,))                          # 仅参数类型匹配
```

要点（源码事实）：

- 每个字段为正则（`re.search`），`None` 表示该维度不限；字段间为**与**关系（所有已配置维度都命中才算命中）。
- `matches(target)` 把目标完整名（`module.Class.method`）按 `.` 右拆三者；目标不含方法层级（裸类名 `_Model`）时跳过 method 校验，避免对无方法目标误判。
- 切点仅作**匹配规则**（与具体实现无关），由 `Aspect` / `AspectRegistry` / `AspectWeaver` 复用。

## 3. 通知：Advice / AdviceType

```python
from web_infra import Advice, AdviceType

# 通知类型（对齐 Spring AOP 语义）
AdviceType.BEFORE          # 方法执行前
AdviceType.AFTER           # 方法执行后（无论成败）
AdviceType.AFTER_RETURNING # 方法成功返回后
AdviceType.AFTER_THROWING  # 方法抛异常后
AdviceType.AROUND          # 包裹整个方法执行

# 通知载体：类型 + 处理函数 + 切面内顺序
advice = Advice(
    type=AdviceType.BEFORE,
    fn=my_before_handler,     # 入参 AspectContext（见下）
    order=0,                  # 切面内通知顺序（升序执行；见 §5）
)
```

`Advice.fn` 统一签名：入参为 `AspectContext`，返回任意值；**AROUND 通知需自行调用 `ctx.proceed()`** 推进到下一层：

```python
from web_infra.core.aop.weaver import AspectContext

# AspectContext 字段
ctx.args      # 方法位置参数
ctx.kwargs    # 方法关键字参数
ctx.proceed   # 下一层调用函数（async 时返回 awaitable）
```

要点：**AROUND 通知是主链路**——切面内存在 AROUND 时由它调用 `proceed`；否则框架内联执行 BEFORE→方法→AFTER 组合（源码事实：`weaver.py::_dispatch` / `_run_async`）。

## 4. 切面：Aspect

```python
from web_infra import Aspect

aspect = Aspect(
    name="transactional",         # 切面名（注册表键，须唯一）
    pointcut=Pointcut(...),       # 切点匹配规则
    advices=(advice_a, advice_b), # 通知集合（按元组顺序执行）
    order=0,                      # 切面间嵌套排序（升序）
)
```

要点：切面是**切点 + 一组通知**的解耦单元；`advices` 的声明顺序决定了切面内通知的执行顺序（`Advice.order` 默认 0，weaver 稳定排序，等于 0 时即枚举顺序，见 §5）。

## 5. 切面注册与顺序语义（重点）

```python
from web_infra import AspectRegistry

AspectRegistry.register(aspect, overwrite=False)   # 同名默认拒绝；overwrite=True 显式覆盖
AspectRegistry.get("transactional")                # 按名查询，未注册返回 None
AspectRegistry.names()                             # 已登记切面名（按注册顺序）
AspectRegistry.matching(pointcut, target, args=()) # 命中切点且排序后的切面链

AspectRegistry.register(Aspect(name="", ...))      # 切面名为空会抛 ValueError
```

**顺序语义（决定嵌套执行顺序，必须在写切面时明确）**：

- `order` **升序、越小越外层**（从小到大由外及里）。例如 order=1 的切面先进入（在世界之外包住 order=5 的切面），即最小 order 属于最外层。
- **同 order 按注册序兜底**：注册越早越靠外层（跨进程稳定，避免依赖字典哈希序）。
- **切面内**一条 AOP 链中多个通知按 `advices` 元组顺序执行（源码：weaver 对 `aspect.advices` 按 `Advice.order` 做**稳定排序**，默认 order=0 时即元组枚举顺序，故呈「声明顺序」）。同一切面内多个同类型通知同样按此顺序，不依赖注册序。
- 排序统一由 `AspectRegistry.matching` / `AspectWeaver` 执行：`hit.sort(key=lambda a: (a.order, 注册序))`。

> 一句话：**order 决定切面间的外围/内层，advices 顺序决定切面内通知的执行次序；两者互不干扰。**

## 6. 织入：AspectWeaver / @aspect

```python
from web_infra import AspectWeaver, aspect

# 业务入口装饰器：织入命中切面（未命中切面则原样返回）
aspect(fn)

# 底层调用等价
AspectWeaver.instance().weave(fn)
```

`AspectWeaver.weave(fn)` 流程（源码事实）：取目标完整名（`module.qualname`）→ `AspectRegistry` 全量命中切面且按 `(order, 注册序)` 排序 → 命中链从最小 order 开始**倒序 wrap**，使最小 order 的切面处于最外层（执行时最先进入）。同步/异步函数统一支持（`inspect.iscoroutinefunction` 分支）。

## 7. 组件访问器：get_component / all_components

Advice 在运行时要拿已装配组件（db/cache 等），通过组件访问器（经 ContextVar，asyncio 场景安全）：

```python
from web_infra import get_component, all_components, bind_components

bind_components({"db": ..., "cache": ...})   # Application 装配完成后由框架自动调用

db = get_component("db")          # 按名取组件；未绑定/不存在返回 None
cache = get_component("cache")
all_components()                  # 当前组件字典副本（测试切片 mock_component 用它"替换单组件后回绑全量"）
```

> 无需在 Advice 中直接依赖全局单例；`Application.build()` 在组件装配后调用 `bind_components(self._components)`，之后 Advice 运行时即可按名取组件（源码：`application.py` / `component_registry.py`）。

## 8. 声明式事务：@transactional

```python
from web_infra import transactional
from web_infra.capabilities.db.transaction_propagation import Propagation, current_session

@transactional(propagation=Propagation.REQUIRED, isolation_level=None)   # 工厂：指定传播/隔离级别
async def create_order(order: dict) -> int:
    session = current_session()        # 方法内取当前事务会话（不注入 session 参数）
    ...
    return order_id

@transactional                          # 裸写：默认 Propagation.REQUIRED（可参数化装饰器）
async def create_order_default(order: dict) -> int:
    session = current_session()
    ...
    return order_id
```

**真实接口签名**（可参数化装饰器：裸写 `@transactional` 与 `@transactional(...)` 均可用）：

```python
def transactional(
    fn: Callable[..., Any] | Propagation | None = None,   # 裸写时被装饰函数；或位置传 Propagation
    *,
    propagation: Propagation = Propagation.REQUIRED,
    isolation_level: str | None = None,
) -> Callable[..., Any]:
    ...
```

- **传播级别**（`Propagation`，对齐 Spring）：
  - `REQUIRED`（默认）：已有活动事务则复用外层，否则新建；
  - `REQUIRES_NEW`：总是新建独立事务（挂起外层）；
  - `NESTED`：基于外层事务开启 SAVEPOINT；无外层时等同 REQUIRED。
- **隔离级别**（`isolation_level`）：仅对支持的环境透传；目标 `session` 不接受该参数时（如 SQLite 参考实现）静默忽略（不 `TypeError`），仅传 `propagation`（源码：`transactional.py::_open_session` 用 `inspect.signature` 探测）。
- **方法内取会话**：**不注入 session 参数**，业务在方法体里用 `current_session()` 取当前事务会话执行 SQL；方法退出统一 commit，异常统一 rollback（含 rollback-only 语义）。
- **裸写 `@transactional` 可用**：为可参数化装饰器——`@transactional`（不带括号，默认 `REQUIRED`）与 `@transactional(propagation=...)` / `@transactional(Propagation.X)`（位置或关键字指定传播级别）三种写法等价（源码：`transactional.py::transactional` 用 `callable(fn)` 判断裸写、`isinstance(fn, Propagation)` 识别位置传传播级别）。
- 运行时取不到 `db` 组件（未 `create_app()` / 未 `bind_components({'db': ...})`）时抛 `RuntimeError`。

> **实现方式（重要）**：`@transactional` 为「装饰器直接织入」，不依赖 `AspectRegistry` 的全局切点匹配。方法进入时开/加入事务，退出或异常时 commit/rollback。**仅 async 函数真正进入事务**；同步函数装饰后仅做组件存在性校验（直接返回原调用，不做事务包裹——框架数据访问均为异步，同步场景无合适异步会话入口，源码事实：`_sync_wrapper`）。

> **与切面 order 的关系**：`register_tx_aspect(order=1)` 会在模块导入时登记一个名为 `transactional` 的**占位切面**（默认切点不匹配任何全局方法），保证事务语义可追溯并保留扩展空间；`@transactional` 实际织入不经过该占位切面。默认 `order=1` 使事务包裹大多数内层切面。

## 9. 声明式缓存：@cacheable / @cache_evict

```python
from web_infra import cacheable, cache_evict

@cacheable("web:order:v1:detail:{0}", ttl=300)      # 命中缓存直接返回；未命中回源并写缓存
async def get_order_detail(order_id: str) -> dict:
    ...

@cache_evict("web:order:v1:detail:{0}")             # 调用目标函数前先删缓存（写后置失效）
async def update_order(order_id: str, payload: dict) -> None:
    ...
```

**真实接口签名**：

```python
def cacheable(key_template: str, *, ttl: int | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...
def cache_evict(key_template: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...
```

**关键点（务必遵守）**：

- **仅支持 async 函数**：后端缓存接口为异步（`CacheBackendInterface`），装饰同步函数在装饰时直接抛 `RuntimeError("cacheable/cache_evict 仅支持 async 函数")`。
- **普通装饰器，不参与切面 order**：`@cacheable` / `@cache_evict` 不注册进 `AspectRegistry`，与 AOP 切面 order 无关；仅作函数包装（读缓存/回源写缓存、删缓存）。
- **Key**：由 `KeyBuilder` 按模板 + 位置参数构建，占位符 `{0}`、`{1}` 按位置注入（模板 `"web:order:v1:detail:{0}"` + `order_id` → `web:order:v1:detail:1001`）。建议遵循缓存文档的 Key 规范（`web:{module}:v1:{biz}`）。
- **缓存变更不绑定事务提交时机**：`@cacheable` 回源写缓存、`@cache_evict` 删缓存都在**方法执行时**完成，与 `@transactional` 的提交时机无关——若业务要求「事务提交后再失效缓存」，需自行在事务外调用 `cache.delete`（见 [缓存文档](./07-缓存.md) §10 的一致性问题）。
- 运行时取不到 `cache` 组件（未 `create_app()` / 未 `bind_components({'cache': ...})`）时抛 `RuntimeError`。

## 10. 书写顺序约定

**装饰器书写顺序（离函数最近的生效顺序）决定了横切执行的先后，建议事务写在最上方**：

```python
@transactional(...)        # 最外层（先进入事务，后包裹其余横切）
@cacheable(...)            # 次外层（在事务内做缓存命中/回源）
def ...
```

解释：Python 装饰器自下而上应用。把 `@transactional` 写在最上方意味着它是最外层包装（先进入、后退出）——事务先开启，包裹缓存读写等内部逻辑，从而保证「缓存失效发生在事务内、随事务一起提交/回滚」。这与面向切面的「order 越小越外层」语义一致。

> 若你使用自定义切面，应把 `@aspect`（或 `@transactional`）放在最上方作为最外层，使其包裹更内层的横切逻辑。

## 11. 最小可运行示例

完整接入 `@transactional`、`@cacheable` / `@cache_evict` 的最小应用：

```python
# service.py —— 业务方法：事务 + 缓存
from web_infra import transactional, cacheable, cache_evict
from web_infra.capabilities.db.transaction_propagation import current_session, Propagation

class OrderService:
    @transactional(propagation=Propagation.REQUIRED)
    @cacheable("web:order:v1:detail:{0}", ttl=300)
    async def get_order_detail(self, order_id: str) -> dict:
        session = current_session()                       # 方法内取当前事务会话
        row = await session.query_one("SELECT * FROM t_order WHERE id=%s", (order_id,))
        return row

    @transactional(propagation=Propagation.REQUIRED)
    @cache_evict("web:order:v1:detail:{0}")
    async def update_order_status(self, order_id: str, status: int) -> None:
        session = current_session()
        await session.execute("UPDATE t_order SET status=%s WHERE id=%s", (status, order_id))
```

自定义切面（记录方法执行耗时）接入同一织入体系：

```python
# aspect.py —— 自定义 AROUND 切面
import time
from web_infra import Pointcut, Advice, AdviceType, Aspect, AspectRegistry, aspect

def _time_around(ctx):
    start = time.perf_counter()
    try:
        return ctx.proceed(*ctx.args, **ctx.kwargs)
    finally:
        print(f"elapsed={time.perf_counter() - start:.3f}s")

timing_aspect = Aspect(
    name="timing",
    pointcut=Pointcut(class_="OrderService"),   # 命中 OrderService 类下所有方法
    advices=(Advice(type=AdviceType.AROUND, fn=_time_around),),
    order=50,                                    # 大 order → 包裹在事务（order=1）内层
)
AspectRegistry.register(timing_aspect)

@aspect                               # 织入命中切面
async def some_business(): ...
```

## 12. 常见坑

1. **切面无命中仍以为生效**：`aspect` 用**目标完整名**（module.Class.method）匹配切点，`__qualname__` 含类名。模块/类名正则写错会导致切面静默不命中；建议用 `AspectRegistry.matching(pointcut, target)` 校验。
2. **order 记反**：order **升序、越小越外层**。想要「先审计后事务」应把审计切面 order 设为更小（更外层）。
3. **对同步方法用 cacheable**：`@cacheable`/`@cache_evict` 装饰同步函数会直接抛 `RuntimeError`——缓存后端是异步接口，请改用 async 函数。
4. **缓存与事务时序错位**：`@cacheable`/`@cache_evict` 的缓存读写发生在方法内，不随事务提交时机；需要「提交后再失效」请自行在事务外删缓存。
5. **事务方法内没取到 session**：必须在 `@transactional` 方法体内用 `current_session()`；装饰器不会注入 session 参数。
6. **同名切面重复注册**：`AspectRegistry.register` 同名默认拒绝，需要显式覆盖时传 `overwrite=True`。
7. **未装配组件**：Advice / 事务 / 缓存运行时按 `get_component` 取组件，务必先 `create_app()`（或测试切片 `web_test_context`）完成 `bind_components`，否则抛 `RuntimeError`。
