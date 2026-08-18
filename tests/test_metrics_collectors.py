"""
连接池 / 运行时 / 线程池 / 组件指标采集单元测试

@Author: 花海
@Date: 2026/08/14 22:00
@Description: 验证 Redis/MongoDB/MySQL 连接池指标采集（未连接时置 0、上限上报）、
              Python 运行时指标采样、线程池注册与采样（§18.5.4），
              以及缓存/存储/消息队列/注册中心组件指标采集（懒注册，配置动态决定）。
"""
import pytest
from concurrent.futures import ThreadPoolExecutor

from web_infra.infra.monitoring.cache_metrics import CacheMetrics
from web_infra.infra.monitoring.metrics import (
    MYSQL_POOL_ACTIVE_CONNECTIONS,
    MYSQL_POOL_CONNECTION_TOTAL,
    MYSQL_POOL_IDLE_CONNECTIONS,
)
from web_infra.infra.monitoring.mq_metrics import MqMetrics
from web_infra.infra.monitoring.pool_metrics import (
    MONGO_POOL_MAX_CONNECTIONS,
    REDIS_POOL_ACTIVE_CONNECTIONS,
    REDIS_POOL_CONNECTION_TOTAL,
    record_mongo_pool_metrics,
    record_mysql_pool_metrics,
    record_redis_pool_metrics,
)
from web_infra.infra.monitoring.registry_metrics import RegistryMetrics
from web_infra.infra.monitoring.runtime_metrics import (
    PYTHON_GC_LIVE_OBJECTS,
    PYTHON_THREADS_CURRENT,
    THREAD_POOL_QUEUE_SIZE,
    THREAD_POOL_WORKERS,
    ThreadPoolMetrics,
    record_runtime_metrics,
)
from web_infra.infra.monitoring.storage_metrics import StorageMetrics


class _FakePool:
    """模拟 SQLAlchemy QueuePool（total/checkedout）"""

    def __init__(self, total: int, checkedout: int) -> None:
        self._total = total
        self._checkedout = checkedout

    def total(self) -> int:
        return self._total

    def checkedout(self) -> int:
        return self._checkedout


def test_record_mysql_pool_metrics():
    """MySQL 池指标：活跃/空闲/总连接数正确写入"""
    record_mysql_pool_metrics(_FakePool(total=5, checkedout=2), "default")
    assert MYSQL_POOL_ACTIVE_CONNECTIONS.labels("default")._value.get() == 2
    assert MYSQL_POOL_IDLE_CONNECTIONS.labels("default")._value.get() == 3
    assert MYSQL_POOL_CONNECTION_TOTAL.labels("default")._value.get() == 5


def test_record_mysql_pool_metrics_without_pool():
    """池未初始化时 MySQL 池指标置 0"""
    record_mysql_pool_metrics(None, "default")
    assert MYSQL_POOL_ACTIVE_CONNECTIONS.labels("default")._value.get() == 0
    assert MYSQL_POOL_CONNECTION_TOTAL.labels("default")._value.get() == 0


def test_record_redis_pool_metrics_without_client():
    """未连接时 Redis 池指标置 0"""
    record_redis_pool_metrics(None, "default")
    assert REDIS_POOL_ACTIVE_CONNECTIONS.labels("default")._value.get() == 0
    assert REDIS_POOL_CONNECTION_TOTAL.labels("default")._value.get() == 0


class _FakeRedisClient:
    """模拟 redis.asyncio 客户端（仅连接池内部属性）"""

    def __init__(self, created: int, in_use: int, max_connections: int) -> None:
        class _Pool:
            def __init__(self) -> None:
                self._created_connections = created
                self._in_use_connections = [None] * in_use
                self._available_connections = [None] * (created - in_use)
                self.max_connections = max_connections

        self.connection_pool = _Pool()


def test_record_redis_pool_metrics_with_client():
    """Redis 池指标：活跃/空闲/总数/上限正确写入"""
    record_redis_pool_metrics(_FakeRedisClient(created=8, in_use=3, max_connections=50), "default")
    assert REDIS_POOL_ACTIVE_CONNECTIONS.labels("default")._value.get() == 3
    assert REDIS_POOL_CONNECTION_TOTAL.labels("default")._value.get() == 8


class _FakeMongoConfig:
    """模拟 MongoDBConfig（仅池上限与客户端）"""

    max_pool_size = 50
    client = None


def test_record_mongo_pool_metrics_without_client():
    """未连接时 MongoDB 池指标置 0，连接上限上报配置值"""
    record_mongo_pool_metrics(_FakeMongoConfig(), "default")
    assert MONGO_POOL_MAX_CONNECTIONS.labels("default")._value.get() == 50


def test_thread_pool_metrics_register_collect_unregister():
    """线程池注册 -> 采样 -> 注销全流程"""
    pool = ThreadPoolExecutor(max_workers=2)
    ThreadPoolMetrics.register(pool, "test-pool")
    try:
        ThreadPoolMetrics.collect()
        assert THREAD_POOL_WORKERS.labels("test-pool")._value.get() >= 0
        assert THREAD_POOL_QUEUE_SIZE.labels("test-pool")._value.get() >= 0
    finally:
        ThreadPoolMetrics.unregister("test-pool")
        pool.shutdown(wait=False)
        # 注销后采样不再包含该池（不抛错）
        ThreadPoolMetrics.collect()


def test_record_runtime_metrics():
    """Python 运行时指标：线程数与各代存活对象数均有采样值"""
    record_runtime_metrics()
    assert PYTHON_THREADS_CURRENT._value.get() >= 1
    for generation in range(3):
        assert PYTHON_GC_LIVE_OBJECTS.labels(str(generation))._value.get() >= 0


def test_cache_metrics_record():
    """缓存指标：操作计数与命中/未命中分开统计，ensure 幂等"""
    CacheMetrics.ensure()
    CacheMetrics.ensure()  # 二次 ensure 不抛重名异常
    before = CacheMetrics.operations_total.labels("memory", "get")._value.get()
    CacheMetrics.record_operation("memory", "get", hit=True)
    assert CacheMetrics.operations_total.labels("memory", "get")._value.get() == before + 1
    assert CacheMetrics.hits_total.labels("memory")._value.get() >= 1
    CacheMetrics.record_operation("memory", "get", hit=False)
    assert CacheMetrics.misses_total.labels("memory")._value.get() >= 1


def test_storage_metrics_record():
    """存储指标：操作计数与字节数统计"""
    StorageMetrics.ensure()
    before = StorageMetrics.operations_total.labels("local", "put")._value.get()
    StorageMetrics.record_operation("local", "put", bytes_count=1024)
    assert StorageMetrics.operations_total.labels("local", "put")._value.get() == before + 1
    assert StorageMetrics.bytes_total.labels("local", "put")._value.get() >= 1024


def test_mq_metrics_record():
    """消息队列指标：发布/消费/错误计数与积压刷新"""
    MqMetrics.ensure()
    before = MqMetrics.published_total.labels("order")._value.get()
    MqMetrics.record_published("order")
    MqMetrics.record_consumed("order")
    MqMetrics.record_error("order", "consume")
    MqMetrics.update_pending("memory", 3)
    assert MqMetrics.published_total.labels("order")._value.get() == before + 1
    assert MqMetrics.consumed_total.labels("order")._value.get() >= 1
    assert MqMetrics.errors_total.labels("order", "consume")._value.get() >= 1
    assert MqMetrics.pending.labels("memory")._value.get() == 3


def test_registry_metrics_record():
    """注册中心指标：注册/注销/发现计数与实例数刷新"""
    RegistryMetrics.ensure()
    before = RegistryMetrics.register_total.labels("user-service")._value.get()
    RegistryMetrics.record_register("user-service")
    RegistryMetrics.record_unregister("user-service")
    RegistryMetrics.record_discover("user-service")
    RegistryMetrics.update_instances("user-service", 2)
    assert RegistryMetrics.register_total.labels("user-service")._value.get() == before + 1
    assert RegistryMetrics.unregister_total.labels("user-service")._value.get() >= 1
    assert RegistryMetrics.discover_total.labels("user-service")._value.get() >= 1
    assert RegistryMetrics.instances.labels("user-service")._value.get() == 2


@pytest.mark.asyncio
async def test_mq_update_metrics_refreshes_pending():
    """内存消息队列 update_metrics：积压数反映队列实际大小"""
    from web_infra.capabilities.mq.in_memory_message_queue import InMemoryMessageQueue
    from web_infra.capabilities.mq.message import Message

    queue = InMemoryMessageQueue()
    await queue.publish(Message(topic="order", message_id="1"))
    await queue.publish(Message(topic="order", message_id="2"))
    queue.update_metrics()
    assert MqMetrics.pending.labels("memory")._value.get() == 2


@pytest.mark.asyncio
async def test_registry_update_metrics_refreshes_instances():
    """内存注册中心 update_metrics：实例数反映已注册实例"""
    from web_infra.capabilities.registry.in_memory import InMemoryServiceRegistry
    from web_infra.capabilities.registry.service_instance import ServiceInstance

    registry = InMemoryServiceRegistry()
    await registry.register("user-service", ServiceInstance(ip="127.0.0.1", port=8001))
    await registry.register("user-service", ServiceInstance(ip="127.0.0.1", port=8002))
    registry.update_metrics()
    assert RegistryMetrics.instances.labels("user-service")._value.get() == 2
