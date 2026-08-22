"""
事件总线单元测试

@Author: 花海
@Date: 2026/08/22 17:00
@Description: 验证 ApplicationEvent 基类、@event_listener 声明式注册、精确/父类匹配、
              EventBus 发布（同步/异步、异常隔离 fail_fast、order 顺序），
              以及事务同步回调 after_commit（注册/触发/清空、提交成功触发/回滚不触发集成）。
"""
import pytest

from web_infra.capabilities.event.event import ApplicationEvent
from web_infra.capabilities.event.event_bus import EventBus
from web_infra.capabilities.event.listener_decorator import event_listener
from web_infra.capabilities.event.listener_registry import EventListenerRegistry


class OrderCreatedEvent(ApplicationEvent):
    event_name = "order.created"


class PaymentSucceededEvent(ApplicationEvent):
    event_name = "payment.succeeded"


def test_event_base_class():
    """ApplicationEvent：默认 event_name 取自类属性，payload/trace_id 可传"""
    ev = OrderCreatedEvent(payload={"order_id": 1}, trace_id="t1")
    assert ev.event_name == "order.created"
    assert ev.payload == {"order_id": 1}
    assert ev.trace_id == "t1"
    assert ev.published_at > 0


def test_listener_registry_exact_and_parent_match(monkeypatch):
    """注册表：精确 event_name 匹配 + 父类 isinstance 匹配"""
    from web_infra.capabilities.event.listener_registry import _clear

    _clear()

    received = []

    @event_listener("order.created")
    async def handle_order(event):
        received.append(event)

    ev = OrderCreatedEvent(payload={"order_id": 1})
    handlers = EventListenerRegistry.match(ev)
    assert len(handlers) == 1
    _clear()


def test_listener_registry_preserves_order(monkeypatch):
    """注册表：同事件多监听器按 order 升序执行"""
    from web_infra.capabilities.event.listener_registry import _clear

    _clear()

    received = []

    @event_listener("order.created", order=1)
    async def first(event):
        received.append("first")

    @event_listener("order.created", order=0)
    async def second(event):
        received.append("second")

    handlers = EventListenerRegistry.match(OrderCreatedEvent(payload={}))
    # order 升序 -> second(order=0) 先，first(order=1) 后
    assert received == []
    _clear()


@pytest.mark.asyncio
async def test_event_bus_publish_sync_handlers():
    """EventBus 发布：同步分发按 order 顺序执行"""
    from web_infra.capabilities.event.listener_registry import _clear

    _clear()

    received = []

    @event_listener("order.created", order=1)
    def first(event):
        received.append("first")

    @event_listener("order.created", order=0)
    def second(event):
        received.append("second")

    bus = EventBus()
    await bus.publish(OrderCreatedEvent(payload={}))
    assert received == ["second", "first"]
    _clear()


@pytest.mark.asyncio
async def test_event_bus_publish_async_handlers_and_fail_isolation():
    """EventBus 发布：异步监听器分发 + 单监听器异常不阻断其余（fail_fast=False）"""
    from web_infra.capabilities.event.listener_registry import _clear

    _clear()

    received = []

    @event_listener("order.created", async_mode=True)
    async def ok(event):
        received.append("ok")

    @event_listener("order.created", async_mode=True)
    async def boom(event):
        raise RuntimeError("listener failed")

    bus = EventBus()
    await bus.publish(OrderCreatedEvent(payload={}))
    assert "ok" in received
    _clear()


# ------------------------------------------------------------------
# Task 6: 事务同步回调（AFTER_COMMIT）——注册/触发/清空 + 提交/回滚集成
# ------------------------------------------------------------------
from web_infra.capabilities.db import SqliteSessionFactory
from web_infra.capabilities.db import transaction_synchronization as ts
from web_infra.capabilities.db.transaction_propagation import current_session
from web_infra.capabilities.db.transaction_synchronization import (
    register_callback,
    trigger_after_commit,
)
from web_infra.capabilities.db.transactional import transactional as _tx
from web_infra.core.aop import bind_components


@pytest.mark.asyncio
async def test_after_commit_registration_and_trigger():
    """注册 after_commit 回调并触发：提交成功后调用"""
    ts._CALLBACKS.set(())
    fired: list[str] = []

    def cb():
        fired.append("cb")

    register_callback(cb)
    await trigger_after_commit()
    assert fired == ["cb"]
    ts._CALLBACKS.set(())


@pytest.mark.asyncio
async def test_after_commit_clear_between_events():
    """每次事务提交后清空回调（防跨事件累积触发）"""
    ts._CALLBACKS.set(())
    fired: list[str] = []

    def cb():
        fired.append("cb")

    register_callback(cb)
    await trigger_after_commit()
    await trigger_after_commit()  # 第二次不应触发（已清空）
    assert len(fired) == 1
    ts._CALLBACKS.set(())


@pytest.mark.asyncio
async def test_after_commit_fires_only_on_commit(tmp_path):
    """提交成功后触发 after_commit；回滚不触发（真实 SqliteSessionFactory + @transactional）"""
    ts._CALLBACKS.set(())
    fired: list[str] = []
    fac = SqliteSessionFactory(db_path=str(tmp_path / "ev.db"))
    fac.create_session().execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")

    class _Fac:
        """模拟真实 SqliteSessionFactory.session(propagation=...) 签名（无 isolation_level）"""

        def session(self, propagation=None):
            return fac.session(propagation=propagation)

    bind_components({"db": _Fac()})

    @_tx()
    async def do_ok():
        s = current_session()
        s.execute("INSERT INTO t (id, name) VALUES (1, 'a')")
        register_callback(lambda: fired.append("commit"))

    await do_ok()
    assert fired == ["commit"]

    fired.clear()

    @_tx()
    async def do_fail():
        s = current_session()
        s.execute("INSERT INTO t (id, name) VALUES (2, 'b')")
        register_callback(lambda: fired.append("commit"))
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await do_fail()
    assert fired == []  # 回滚不触发
    ts._CALLBACKS.set(())
    fac.close()


# ------------------------------------------------------------------
# Task 9: 顶层导出（最小安装无第三方依赖）
# ------------------------------------------------------------------
def test_top_level_exports():
    """顶层导出事件总线/AOP/声明式事务与缓存/测试切片符号（最小安装无第三方依赖）"""
    import web_infra

    assert web_infra.ApplicationEvent is not None
    assert web_infra.EventBus is not None
    assert web_infra.event_listener is not None
    assert web_infra.transactional is not None
    assert web_infra.cacheable is not None
    assert web_infra.cache_evict is not None
    assert web_infra.web_test_context is not None
    assert web_infra.Aspect is not None
    assert web_infra.Pointcut is not None


# ------------------------------------------------------------------
# 事件总线核心化（始终装配）与框架启动/停机生命周期事件
# ------------------------------------------------------------------
def test_application_event_always_assembled():
    """事件总线作为核心能力：create_app 后始终装配 EventBus 到 app.state.event（无需 app.event.enabled）"""
    from web_infra import create_app

    app = create_app({"app.name": "test-app"})
    assert isinstance(app.state.event, EventBus)


def test_application_lifecycle_events_order():
    """生命周期事件顺序：starting -> ready -> stopping -> stopped（TestClient 上下文触发完整 lifespan）"""
    from fastapi.testclient import TestClient

    from web_infra import create_app

    EventListenerRegistry.clear()
    events: list[str] = []

    @event_listener("application_starting")
    def on_starting(event):
        events.append("application_starting")

    @event_listener("application_ready")
    def on_ready(event):
        events.append("application_ready")

    @event_listener("application_stopping")
    def on_stopping(event):
        events.append("application_stopping")

    @event_listener("application_stopped")
    def on_stopped(event):
        events.append("application_stopped")

    app = create_app({"app.name": "test-app"})
    with TestClient(app) as client:
        pass

    assert events == ["application_starting", "application_ready", "application_stopping", "application_stopped"]
    EventListenerRegistry.clear()


@pytest.mark.asyncio
async def test_event_bus_fail_fast_rethrows():
    """fail_fast=True：监听器异常向上抛（不静默隔离）"""
    from web_infra.capabilities.event.listener_registry import _clear

    _clear()

    @event_listener("order.created")
    def boom(event):
        raise RuntimeError("listener failed")

    bus = EventBus(fail_fast=True)
    with pytest.raises(RuntimeError, match="listener failed"):
        await bus.publish(OrderCreatedEvent(payload={}))
    _clear()
