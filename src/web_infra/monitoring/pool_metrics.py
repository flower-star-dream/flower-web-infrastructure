"""
连接池运行指标采集模块

@Author: 花海
@Date: 2026/08/14 22:00
@Description: 按规范 §18.5.4 采集 MySQL / Redis / MongoDB 连接池运行指标（活跃/空闲/总连接数、上限、泄漏计数）。
              各配置类在连接建立、健康检查或 /metrics 抓取时调用对应 record_* 函数刷新 Gauge；
              池未连接或内部状态不可读时置 0，保证页面/采集端始终有确定值。
"""
from __future__ import annotations

from typing import Any

from prometheus_client import Gauge, Histogram

from web_infra.monitoring.metrics import (
    MYSQL_POOL_ACQUIRE_SECONDS,
    MYSQL_POOL_ACTIVE_CONNECTIONS,
    MYSQL_POOL_CONNECTION_TOTAL,
    MYSQL_POOL_IDLE_CONNECTIONS,
    MYSQL_POOL_WAITING_CONNECTIONS,
    PHASE_LATENCY_BUCKETS,
)

# Redis 连接池指标（§18.5.4，datasource 低基数标签）
REDIS_POOL_ACTIVE_CONNECTIONS = Gauge("redis_pool_active_connections", "Redis 连接池活跃连接数", ["datasource"])
REDIS_POOL_IDLE_CONNECTIONS = Gauge("redis_pool_idle_connections", "Redis 连接池空闲连接数", ["datasource"])
REDIS_POOL_CONNECTION_TOTAL = Gauge("redis_pool_connection_total", "Redis 连接池总连接数", ["datasource"])
REDIS_POOL_MAX_CONNECTIONS = Gauge("redis_pool_max_connections", "Redis 连接池连接上限", ["datasource"])
# 连接池等待与获取耗时（§18.5.4 扩展：等待数 Gauge + 获取耗时直方图，低基数 datasource 标签）
REDIS_POOL_WAITING_CONNECTIONS = Gauge("redis_pool_waiting_connections", "Redis 连接池等待连接数", ["datasource"])
REDIS_POOL_ACQUIRE_SECONDS = Histogram("redis_pool_acquire_seconds", "Redis 连接获取耗时分布", ["datasource"], buckets=PHASE_LATENCY_BUCKETS)

# MongoDB 连接池指标（§18.5.4，datasource 低基数标签）
MONGO_POOL_ACTIVE_CONNECTIONS = Gauge("mongo_pool_active_connections", "MongoDB 连接池活跃连接数", ["datasource"])
MONGO_POOL_IDLE_CONNECTIONS = Gauge("mongo_pool_idle_connections", "MongoDB 连接池空闲连接数", ["datasource"])
MONGO_POOL_CONNECTION_TOTAL = Gauge("mongo_pool_connection_total", "MongoDB 连接池总连接数", ["datasource"])
MONGO_POOL_MAX_CONNECTIONS = Gauge("mongo_pool_max_connections", "MongoDB 连接池连接上限", ["datasource"])
# 连接池等待与获取耗时（§18.5.4 扩展：等待数 Gauge + 获取耗时直方图，低基数 datasource 标签）
MONGO_POOL_WAITING_CONNECTIONS = Gauge("mongo_pool_waiting_connections", "MongoDB 连接池等待连接数", ["datasource"])
MONGO_POOL_ACQUIRE_SECONDS = Histogram("mongo_pool_acquire_seconds", "MongoDB 连接获取耗时分布", ["datasource"], buckets=PHASE_LATENCY_BUCKETS)


def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    """容错读取对象属性（连接池内部实现随驱动版本变化，读取失败回退默认值）"""
    return getattr(obj, name, default) if obj is not None else default


def record_mysql_pool_metrics(pool: Any, datasource: str = "default", waiting: int | None = None) -> None:
    """刷新 MySQL 连接池指标（SQLAlchemy QueuePool，未初始化时各项置 0）。

    :param pool: SQLAlchemy sync_engine.pool（QueuePool）
    :param datasource: 数据源名称（低基数标签）
    :param waiting: 当前等待获取连接的请求数；缺省不刷新等待数指标（由驱动事件监听提供时传入）
    """
    if pool is None:
        total = checkedout = 0
    else:
        try:
            total = int(pool.total())
            checkedout = int(pool.checkedout())
        except Exception:  # 池状态异常时按未连接处理，避免采集端报错
            total = checkedout = 0
    MYSQL_POOL_ACTIVE_CONNECTIONS.labels(datasource).set(checkedout)
    MYSQL_POOL_IDLE_CONNECTIONS.labels(datasource).set(max(total - checkedout, 0))
    MYSQL_POOL_CONNECTION_TOTAL.labels(datasource).set(total)
    if waiting is not None:
        MYSQL_POOL_WAITING_CONNECTIONS.labels(datasource).set(max(int(waiting), 0))


def record_mysql_pool_acquire(datasource: str = "default", seconds: float = 0.0) -> None:
    """记录一次 MySQL 连接获取耗时（骨架：由 mysql_config 连接获取路径调用）"""
    MYSQL_POOL_ACQUIRE_SECONDS.labels(datasource).observe(max(seconds, 0.0))


def record_redis_pool_metrics(client: Any, datasource: str = "default", waiting: int | None = None) -> None:
    """刷新 Redis 连接池指标（redis.asyncio ConnectionPool 内部状态）。

    连接池未建立或内部属性缺失时各指标置 0（不同 redis-py 版本私有属性名可能不同）。

    :param client: redis.asyncio.Redis 客户端实例
    :param datasource: 数据源名称（低基数标签）
    :param waiting: 当前等待获取连接的请求数；缺省不刷新等待数指标（由驱动事件监听提供时传入）
    """
    pool = _safe_attr(client, "connection_pool")
    if pool is None:
        active = idle = total = max_connections = 0
    else:
        try:
            created = int(_safe_attr(pool, "_created_connections", 0) or 0)
            available = len(_safe_attr(pool, "_available_connections", ()) or ())
            in_use = len(_safe_attr(pool, "_in_use_connections", ()) or ())
            active = in_use
            idle = max(available, 0)
            total = max(created, active + idle)
            max_connections = int(_safe_attr(pool, "max_connections", 0) or 0)
        except Exception:
            active = idle = total = max_connections = 0
    REDIS_POOL_ACTIVE_CONNECTIONS.labels(datasource).set(active)
    REDIS_POOL_IDLE_CONNECTIONS.labels(datasource).set(idle)
    REDIS_POOL_CONNECTION_TOTAL.labels(datasource).set(total)
    REDIS_POOL_MAX_CONNECTIONS.labels(datasource).set(max_connections)
    if waiting is not None:
        REDIS_POOL_WAITING_CONNECTIONS.labels(datasource).set(max(int(waiting), 0))


def record_redis_pool_acquire(datasource: str = "default", seconds: float = 0.0) -> None:
    """记录一次 Redis 连接获取耗时（骨架：由 redis 配置连接获取路径调用）"""
    REDIS_POOL_ACQUIRE_SECONDS.labels(datasource).observe(max(seconds, 0.0))


def record_mongo_pool_metrics(config: Any, datasource: str = "default", waiting: int | None = None) -> None:
    """刷新 MongoDB 连接池指标（PyMongo 底层同步连接池内部状态）。

    客户端未连接或池状态不可读时各指标置 0；连接上限始终上报配置值。

    :param config: MongoDBConfig 实例（持 client 与 max_pool_size）
    :param datasource: 数据源名称（低基数标签）
    :param waiting: 当前等待获取连接的请求数；缺省不刷新等待数指标（由驱动事件监听提供时传入）
    """
    max_connections = int(_safe_attr(config, "max_pool_size", 0) or 0)
    client = _safe_attr(config, "client")
    active = idle = total = 0
    if client is not None:
        try:
            servers = _safe_attr(client, "_topology", None)
            servers = _safe_attr(servers, "_servers", None) or []
            for server in servers:
                pool = _safe_attr(server, "pool", None)
                inner = _safe_attr(pool, "pool")
                if inner is None:
                    continue
                active += len(_safe_attr(inner, "requests", {}) or {})
                idle += len(_safe_attr(inner, "available_connections", ()) or ())
                total += len(_safe_attr(inner, "conns", ()) or ())
        except Exception:
            active = idle = total = 0
    MONGO_POOL_ACTIVE_CONNECTIONS.labels(datasource).set(active)
    MONGO_POOL_IDLE_CONNECTIONS.labels(datasource).set(idle)
    MONGO_POOL_CONNECTION_TOTAL.labels(datasource).set(total)
    MONGO_POOL_MAX_CONNECTIONS.labels(datasource).set(max_connections)
    if waiting is not None:
        MONGO_POOL_WAITING_CONNECTIONS.labels(datasource).set(max(int(waiting), 0))


def record_mongo_pool_acquire(datasource: str = "default", seconds: float = 0.0) -> None:
    """记录一次 MongoDB 连接获取耗时（骨架：由 mongo 配置连接获取路径调用）"""
    MONGO_POOL_ACQUIRE_SECONDS.labels(datasource).observe(max(seconds, 0.0))
