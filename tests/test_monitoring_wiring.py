"""
监控接线整改单元测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证监控/可观测性接线整改：
              - S18-1 分阶段耗时埋点：鉴权中间件 PhaseTimer 埋点后 request_out 日志含 phase 字段
              - S18-2 慢请求样本：有界环形缓存写入/读取/脱敏（含超阈值请求集成）
              - S18-3 慢 SQL 分级计数：record_slow_sql 同步递增 SLOW_SQL_TOTAL 并写明细缓存
              - S18-5 连接池扩展：waiting Gauge / acquire Histogram 定义与记录函数骨架可 set/observe
"""
import asyncio
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web_infra.infra.constants.sys_constant import SysConstant
from web_infra.infra.context import RequestContext
from web_infra.infra.monitoring import metrics
from web_infra.infra.monitoring.metrics import (
    MYSQL_POOL_ACQUIRE_SECONDS,
    MYSQL_POOL_WAITING_CONNECTIONS,
    SLOW_SQL_TOTAL,
)
from web_infra.infra.monitoring.phase_timer import PhaseTimer
from web_infra.infra.monitoring.pool_metrics import (
    MONGO_POOL_ACQUIRE_SECONDS,
    MONGO_POOL_WAITING_CONNECTIONS,
    REDIS_POOL_ACQUIRE_SECONDS,
    REDIS_POOL_WAITING_CONNECTIONS,
    record_mongo_pool_acquire,
    record_mysql_pool_acquire,
    record_mysql_pool_metrics,
    record_redis_pool_acquire,
)
from web_infra.infra.monitoring.slow_request_store import SlowRequestStore
from web_infra.capabilities.security import JWTUtil
from web_infra.infra.web import AuthMiddleware, LoggingMiddleware, TraceIdMiddleware

_SECRET = "test-secret-for-monitoring-wiring-0123456789"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    """注入 JWT 测试密钥"""
    monkeypatch.setenv("JWT_SECRET_KEY", _SECRET)


@pytest.fixture(autouse=True)
def _clean_slow_store():
    """每个测试前清空慢请求样本缓存，避免串扰"""
    SlowRequestStore.instance().clear()
    yield
    SlowRequestStore.instance().clear()


def _build_app() -> FastAPI:
    """构造带 TraceId/鉴权/访问日志三层中间件的测试应用"""
    app = FastAPI()
    app.add_middleware(TraceIdMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(LoggingMiddleware, service_name="test")

    @app.get("/secure")
    async def secure():
        return {"user_id": RequestContext.get_user_id()}

    @app.get("/api/orders/{order_id}")
    async def order(order_id: int):
        return {"order_id": order_id}

    return app


def _token() -> str:
    """签发测试 token"""
    return asyncio.run(JWTUtil.generate_token(user_id="u1", username="tester", extra_claims={"scope": "read"}))


# ---------------------------------------------------------------------------
# 整改 1（S18-1）：分阶段耗时埋点接线
# ---------------------------------------------------------------------------


def test_phase_timer_mark_records_phase():
    """PhaseTimer.mark 写入阶段耗时，to_log_fields 输出 phase_<name>_ms 字段"""
    timer = PhaseTimer.start()
    try:
        PhaseTimer.mark("auth")
        timer.mark_total()
        fields = timer.to_log_fields()
        assert "phase_auth_ms" in fields
        assert "phase_total_ms" in fields
        assert fields["phase_total_ms"] >= fields["phase_auth_ms"]
    finally:
        PhaseTimer.clear()


def test_phase_timer_mark_without_context_is_silent():
    """无 PhaseTimer 上下文时 mark 静默跳过（向后兼容，不影响既有调用方）"""
    PhaseTimer.clear()
    PhaseTimer.mark("auth")  # 不抛错


def test_access_log_contains_uvicorn_format_and_phase(caplog):
    """鉴权通过后访问日志为 uvicorn 标准格式且含分阶段耗时（phase_auth_ms）"""
    client = TestClient(_build_app())
    with caplog.at_level(logging.INFO):
        resp = client.get("/secure", headers={"Authorization": f"Bearer {_token()}"})
    assert resp.status_code == 200
    messages = [r.getMessage() for r in caplog.records]
    assert any('"GET /secure HTTP/1.1"' in m and "phase_auth_ms=" in m and "trace_id=" in m for m in messages)


def test_access_log_contains_phase_on_auth_failure(caplog):
    """鉴权失败（401）路径同样输出访问日志且含分阶段耗时（失败路径埋点）"""
    client = TestClient(_build_app())
    with caplog.at_level(logging.INFO):
        resp = client.get("/secure")
    assert resp.status_code == 401
    messages = [r.getMessage() for r in caplog.records]
    assert any('"GET /secure HTTP/1.1"' in m and "phase_auth_ms=" in m for m in messages)


# ---------------------------------------------------------------------------
# 整改 2（S18-2）：慢请求样本留存
# ---------------------------------------------------------------------------


def test_slow_request_store_record_recent_and_order():
    """样本写入与读取：最近写入的样本排在最前，recent(limit) 生效"""
    store = SlowRequestStore.instance()
    store.record({"trace_id": "t1", "path": "/a", "duration_ms": 5100.0})
    store.record({"trace_id": "t2", "path": "/b", "duration_ms": 5200.0})
    samples = store.recent()
    assert len(samples) == 2
    assert samples[0]["trace_id"] == "t2"
    assert samples[1]["trace_id"] == "t1"
    assert store.recent(limit=1)[0]["trace_id"] == "t2"


def test_slow_request_store_bounded():
    """样本缓存有界：超过 maxlen 时丢弃最旧样本"""
    store = SlowRequestStore.instance()
    for i in range(150):
        store.record({"trace_id": f"t{i}", "duration_ms": float(i)})
    assert store.size == 100
    assert store.recent()[0]["trace_id"] == "t149"
    assert store.recent()[-1]["trace_id"] == "t50"


def test_slow_request_sample_captured_and_masked(monkeypatch):
    """超阈值请求写入样本：路径归一化脱敏 + 请求参数脱敏 + 各阶段耗时齐全"""
    monkeypatch.setattr(SysConstant, "SYS_SLOW_REQUEST_THRESHOLD_MS", 0)
    client = TestClient(_build_app())
    client.get(
        "/api/orders/12345?password=secret123",
        headers={"Authorization": f"Bearer {_token()}"},
    )
    client.get(
        "/api/orders/999?phone=13812341234",
        headers={"Authorization": f"Bearer {_token()}"},
    )
    samples = SlowRequestStore.instance().recent()
    assert len(samples) == 2
    phone_sample = samples[0]  # 最近写入的 phone 请求
    pwd_sample = samples[1]
    for sample in samples:
        assert sample["method"] == "GET"
        assert sample["path"] == "/api/orders/{id}"  # 数字 ID 段归一化脱敏
        assert sample["status_code"] == 200
        assert sample["duration_ms"] >= 0
        assert "phase_auth_ms" in sample["phases"]  # 各阶段耗时随样本留存
        assert "phase_total_ms" in sample["phases"]
        assert sample["trace_id"]
    assert "138****1234" in phone_sample["params"]  # 手机号已打码
    assert "13812341234" not in pwd_sample["params"]
    assert "secret123" not in pwd_sample["params"]  # 密钥已掩码
    assert "password=******" in pwd_sample["params"]


def test_slow_request_total_counter_still_incremented(monkeypatch):
    """超阈值时保留 SLOW_REQUEST_TOTAL 计数（整改 2 不破坏既有计数）"""
    monkeypatch.setattr(SysConstant, "SYS_SLOW_REQUEST_THRESHOLD_MS", 0)
    before = metrics.SLOW_REQUEST_TOTAL.labels("test", "/secure")._value.get()
    client = TestClient(_build_app())
    client.get("/secure", headers={"Authorization": f"Bearer {_token()}"})
    assert metrics.SLOW_REQUEST_TOTAL.labels("test", "/secure")._value.get() == before + 1


# ---------------------------------------------------------------------------
# 整改 3（S18-3）：慢 SQL 计数与分级告警
# ---------------------------------------------------------------------------


def test_record_slow_sql_updates_counter_and_cache():
    """record_slow_sql：分级计数指标递增 + 明细环形缓存更新"""
    metrics.init_metrics("test")
    before = SLOW_SQL_TOTAL.labels("test", "default", "warning")._value.get()
    metrics.record_slow_sql("default", 0.3, "SELECT 1", "warning", "P2")
    assert SLOW_SQL_TOTAL.labels("test", "default", "warning")._value.get() == before + 1

    # 分级语义：critical 级别独立计数
    metrics.record_slow_sql("default", 2.5, "SELECT 2", "critical", "P1")
    assert SLOW_SQL_TOTAL.labels("test", "default", "critical")._value.get() >= 1

    samples = metrics.get_slow_sql_samples()
    assert samples[0]["sql"] == "SELECT 2"
    assert samples[0]["severity"] == "critical"
    assert samples[0]["alert_level"] == "P1"
    assert samples[0]["datasource"] == "default"
    assert samples[0]["duration_ms"] == 2500.0  # 2.5s → 2500ms


def test_metrics_html_slow_sql_help_mentions_severity(monkeypatch):
    """metrics_html 说明区补充慢 SQL 分级计数说明（空缓存文案）"""
    from web_infra.infra.monitoring.metrics_html import _render_slow_sql_detail

    monkeypatch.setattr("web_infra.infra.monitoring.metrics._SLOW_SQL_CACHE", [])
    html = _render_slow_sql_detail()
    assert "slow_sql_total" in html
    assert "severity" in html


# ---------------------------------------------------------------------------
# 整改 4（S18-5 部分）：连接池 waiting / 获取耗时指标
# ---------------------------------------------------------------------------


def test_pool_waiting_and_acquire_metrics_defined():
    """MySQL/Redis/Mongo 等待数与获取耗时指标定义存在且可 set/observe"""
    MYSQL_POOL_WAITING_CONNECTIONS.labels("default").set(2)
    assert MYSQL_POOL_WAITING_CONNECTIONS.labels("default")._value.get() == 2
    MYSQL_POOL_ACQUIRE_SECONDS.labels("default").observe(0.05)
    assert MYSQL_POOL_ACQUIRE_SECONDS.labels("default")._sum.get() == 0.05

    REDIS_POOL_WAITING_CONNECTIONS.labels("default").set(1)
    assert REDIS_POOL_WAITING_CONNECTIONS.labels("default")._value.get() == 1
    REDIS_POOL_ACQUIRE_SECONDS.labels("default").observe(0.02)
    assert REDIS_POOL_ACQUIRE_SECONDS.labels("default")._sum.get() == 0.02

    MONGO_POOL_WAITING_CONNECTIONS.labels("default").set(3)
    assert MONGO_POOL_WAITING_CONNECTIONS.labels("default")._value.get() == 3
    MONGO_POOL_ACQUIRE_SECONDS.labels("default").observe(0.03)
    assert MONGO_POOL_ACQUIRE_SECONDS.labels("default")._sum.get() == 0.03


def test_pool_acquire_record_functions_observe():
    """获取耗时记录函数骨架：observe 写入直方图"""
    record_mysql_pool_acquire("default", 0.04)
    record_redis_pool_acquire("default", 0.01)
    record_mongo_pool_acquire("default", 0.02)
    assert MYSQL_POOL_ACQUIRE_SECONDS.labels("default")._sum.get() >= 0.04
    assert REDIS_POOL_ACQUIRE_SECONDS.labels("default")._sum.get() >= 0.01
    assert MONGO_POOL_ACQUIRE_SECONDS.labels("default")._sum.get() >= 0.02


class _FakePool:
    """模拟 SQLAlchemy QueuePool（total/checkedout）"""

    def __init__(self, total: int, checkedout: int) -> None:
        self._total = total
        self._checkedout = checkedout

    def total(self) -> int:
        return self._total

    def checkedout(self) -> int:
        return self._checkedout


def test_record_mysql_pool_metrics_refreshes_waiting():
    """记录函数 waiting 参数刷新等待数 Gauge；缺省不刷新（保持上次值）"""
    record_mysql_pool_metrics(_FakePool(total=5, checkedout=2), "default", waiting=3)
    assert MYSQL_POOL_WAITING_CONNECTIONS.labels("default")._value.get() == 3
    record_mysql_pool_metrics(_FakePool(total=5, checkedout=2), "default")
    assert MYSQL_POOL_WAITING_CONNECTIONS.labels("default")._value.get() == 3  # 缺省不覆盖
