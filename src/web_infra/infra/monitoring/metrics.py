"""
应用指标采集（prometheus-client）

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 按规范 §18 采集 RED 指标（QPS/错误率/时延）、分阶段耗时（§18.5.1）、慢请求/慢 SQL（§18.5.2/§18.5.3）、
              连接池运行指标（§18.5.4）。指标命名遵循 {模块}.{接口}.{指标}，标签不携带高基数动态值。
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from threading import Lock
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

from web_infra.infra.constants import HttpStatusConstant

_service_name = "unknown"


def init_metrics(service_name: str) -> None:
    """初始化指标服务名标签"""
    global _service_name
    if service_name:
        _service_name = service_name


def _service() -> str:
    """返回当前服务名"""
    return _service_name


HTTP_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
PHASE_LATENCY_BUCKETS = (0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

# RED 指标（§18.1）
HTTP_REQUESTS_TOTAL = Counter("http_requests_total", "HTTP 请求总数", ["service", "method", "path", "status_class"])
HTTP_REQUESTS_IN_FLIGHT = Gauge("http_requests_in_flight", "当前处理中的 HTTP 请求数", ["service"])
HTTP_REQUEST_DURATION_SECONDS = Histogram("http_request_duration_seconds", "HTTP 请求耗时分布", ["service", "method", "path"], buckets=HTTP_LATENCY_BUCKETS)
HTTP_REQUEST_ERRORS_TOTAL = Counter("http_request_errors_total", "HTTP 请求错误总数", ["service", "method", "path"])

# 分阶段耗时（§18.5.1）
REQUEST_PHASE_DURATION_SECONDS = Histogram("request_phase_duration_seconds", "全链路分阶段耗时分布", ["service", "phase"], buckets=PHASE_LATENCY_BUCKETS)

# 慢请求 / 慢 SQL（§18.5.2 / §18.5.3）
SLOW_REQUEST_TOTAL = Counter("slow_request_total", "慢请求次数", ["service", "path"])
SLOW_SQL_TOTAL = Counter("slow_sql_total", "慢 SQL 次数", ["service", "datasource", "severity"])

# MySQL 连接池运行指标（§18.5.4）
MYSQL_POOL_ACTIVE_CONNECTIONS = Gauge("mysql_pool_active_connections", "MySQL 连接池活跃连接数", ["datasource"])
MYSQL_POOL_IDLE_CONNECTIONS = Gauge("mysql_pool_idle_connections", "MySQL 连接池空闲连接数", ["datasource"])
MYSQL_POOL_CONNECTION_TOTAL = Gauge("mysql_pool_connection_total", "MySQL 连接池总连接数", ["datasource"])
MYSQL_POOL_CONNECTION_LEAK_TOTAL = Counter("mysql_pool_connection_leak_total", "MySQL 连接泄漏计数", ["datasource"])
# 连接池等待与获取耗时（§18.5.4 扩展：等待数 Gauge + 获取耗时直方图，低基数 datasource 标签）
MYSQL_POOL_WAITING_CONNECTIONS = Gauge("mysql_pool_waiting_connections", "MySQL 连接池等待连接数", ["datasource"])
MYSQL_POOL_ACQUIRE_SECONDS = Histogram("mysql_pool_acquire_seconds", "MySQL 连接获取耗时分布", ["datasource"], buckets=PHASE_LATENCY_BUCKETS)

# 慢 SQL 明细环形缓存（§18.5.3）
SLOW_SQL_CACHE_MAXLEN = 20
_SLOW_SQL_CACHE: deque[dict[str, Any]] = deque(maxlen=SLOW_SQL_CACHE_MAXLEN)
# S16-2 豁免：临界区为纯内存操作，无 I/O 阻塞，不适用 3s 获取超时
_SLOW_SQL_CACHE_LOCK = Lock()


def record_http_request(method: str, path: str, duration_seconds: float, status_code: int, is_error: bool = False, service: str | None = None) -> None:
    """记录一条 HTTP 请求的 RED 指标"""
    service = service or _service()
    if status_code >= HttpStatusConstant.HTTP_SERVER_ERROR_MIN or is_error:
        status_class = "5xx" if status_code >= HttpStatusConstant.HTTP_SERVER_ERROR_MIN else "error"
        HTTP_REQUEST_ERRORS_TOTAL.labels(service, method, path).inc()
    else:
        status_class = str(status_code)
    HTTP_REQUESTS_TOTAL.labels(service, method, path, status_class).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(service, method, path).observe(duration_seconds)


def record_slow_sql(datasource: str, duration_seconds: float, sql: str, severity: str, alert_level: str) -> None:
    """记录慢 SQL：累加计数指标（§18.5.3 slow_sql_total）并缓存明细供查询"""
    SLOW_SQL_TOTAL.labels(_service(), datasource, severity).inc()
    with _SLOW_SQL_CACHE_LOCK:
        _SLOW_SQL_CACHE.appendleft({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "datasource": datasource,
            "duration_ms": round(duration_seconds * 1000.0, 1),
            "sql": sql,
            "severity": severity,
            "alert_level": alert_level,
        })


def get_slow_sql_samples(limit: int = SLOW_SQL_CACHE_MAXLEN) -> list[dict[str, Any]]:
    """返回最近 N 条慢 SQL 明细"""
    with _SLOW_SQL_CACHE_LOCK:
        return list(_SLOW_SQL_CACHE)[:limit]
