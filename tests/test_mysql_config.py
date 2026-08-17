"""
MySQL 数据库配置单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证 MySQLConnectionSettings 结构化配置的 URL 构建与解析（规范 §14.1）、
              SSL 默认开启（S10-3）、三层超时（S14-1）与慢 SQL 指标接线（S18-3）。
"""
import pytest
from sqlalchemy import text

from web_infra.db import MySQLConfig, MySQLConnectionSettings
from web_infra.db.mysql_config import _sql_preview
from web_infra.monitoring.metrics import (
    SLOW_SQL_TOTAL,
    get_slow_sql_samples,
    init_metrics,
    record_slow_sql,
)


def test_mysql_settings_to_url():
    """结构化配置转换为 SQLAlchemy URL"""
    settings = MySQLConnectionSettings(
        host="localhost", port=3306, database="app", username="root", password="pwd"
    )
    assert settings.to_sqlalchemy_url() == "mysql+aiomysql://root:pwd@localhost:3306/app?charset=utf8mb4"


def test_mysql_settings_from_url():
    """URL 解析为结构化配置"""
    settings = MySQLConnectionSettings.from_url("mysql+aiomysql://root:pwd@127.0.0.1:3306/app?charset=utf8mb4")
    assert settings.host == "127.0.0.1"
    assert settings.port == 3306
    assert settings.database == "app"
    assert settings.username == "root"
    assert settings.password == "pwd"
    assert settings.charset == "utf8mb4"


def test_mysql_config_requires_url_or_settings():
    """未提供 url/settings 时抛出 ValueError"""
    with pytest.raises(ValueError):
        MySQLConfig()


# ------------------------------------------------------------------
# 整改 S10-3：SSL 默认开启
# ------------------------------------------------------------------

def test_mysql_settings_ssl_default_enabled():
    """SSL 默认开启 + check_hostname 默认 True，可显式关闭"""
    settings = MySQLConnectionSettings(host="localhost")
    assert settings.use_ssl is True
    assert settings.check_hostname is True
    assert settings.to_connect_args()["ssl"] == {"ca": None, "check_hostname": True}

    disabled = MySQLConnectionSettings(host="localhost", use_ssl=False)
    assert "ssl" not in disabled.to_connect_args()


def test_mysql_settings_usessl_false_disables_ssl():
    """URL 解析：usessl=false 关闭 SSL；URL 缺省时默认开启"""
    settings = MySQLConnectionSettings.from_url("mysql+aiomysql://root:pwd@localhost:3306/app?usessl=false")
    assert settings.use_ssl is False
    assert "ssl" not in settings.to_connect_args()

    enabled = MySQLConnectionSettings.from_url("mysql+aiomysql://root:pwd@localhost:3306/app")
    assert enabled.use_ssl is True


def test_mysql_config_build_url_usessl_mapping():
    """MySQLConfig URL 构建：usessl 参数映射到 connect_args.ssl（默认开启，显式 false 关闭）"""
    config = MySQLConfig(url="mysql+aiomysql://root:pwd@127.0.0.1:3306/app?charset=utf8mb4")
    assert config.connect_args["ssl"] == {"ca": None, "check_hostname": True}

    no_ssl = MySQLConfig(url="mysql+aiomysql://root:pwd@127.0.0.1:3306/app?charset=utf8mb4&usessl=false")
    assert "ssl" not in no_ssl.connect_args


# ------------------------------------------------------------------
# 整改 S14-1：超时（连接建立 / 语句执行两层；aiomysql 不支持 socket 读写超时）
# ------------------------------------------------------------------

def test_mysql_settings_timeouts():
    """超时进入 connect_args：连接建立 + 语句执行；aiomysql 不支持的读写超时参数不注入"""
    settings = MySQLConnectionSettings(
        host="localhost", connect_timeout=5, statement_timeout_seconds=3.0
    )
    args = settings.to_connect_args()
    assert args["connect_timeout"] == 5
    assert "read_timeout" not in args
    assert "write_timeout" not in args
    assert "SET SESSION max_execution_time = 3000" in args["init_command"]

    default = MySQLConnectionSettings(host="localhost")
    default_args = default.to_connect_args()
    assert default_args["connect_timeout"] == 10
    assert "read_timeout" not in default_args
    assert "write_timeout" not in default_args
    assert "SET SESSION max_execution_time" not in default_args["init_command"]


# ------------------------------------------------------------------
# 整改 S18-3：慢 SQL 指标接线
# ------------------------------------------------------------------

def test_record_slow_sql_metric_and_cache():
    """record_slow_sql 累加计数指标并写入明细缓存"""
    init_metrics("test-svc")
    before = SLOW_SQL_TOTAL.labels("test-svc", "default", "warning")._value.get()
    record_slow_sql("default", 0.5, "SELECT * FROM t WHERE id = ?", "warning", "P2")
    after = SLOW_SQL_TOTAL.labels("test-svc", "default", "warning")._value.get()
    assert after == before + 1

    samples = get_slow_sql_samples()
    assert samples[0]["sql"] == "SELECT * FROM t WHERE id = ?"
    assert samples[0]["severity"] == "warning"
    assert samples[0]["alert_level"] == "P2"


def test_sql_preview_masks_literals():
    """SQL 摘要脱敏：引号字面量替换为 ?，参数值不进日志/指标"""
    assert _sql_preview("SELECT * FROM t WHERE name = 'secret'") == "SELECT * FROM t WHERE name = ?"
    assert "'" not in _sql_preview("SELECT * FROM t WHERE a = 'x' AND b = 'y'")
    assert _sql_preview("UPDATE t SET name = 'alice' WHERE id = 1") == "UPDATE t SET name = ? WHERE id = 1"


@pytest.mark.asyncio
async def test_slow_sql_event_calls_record_slow_sql(monkeypatch):
    """慢 SQL 事件触发 record_slow_sql（P2 warning 分支），日志保留"""
    import web_infra.db.mysql_config as mc
    from sqlalchemy.ext.asyncio import create_async_engine as real_create_async_engine

    recorded = []
    monkeypatch.setattr(mc, "record_slow_sql", lambda *args, **kwargs: recorded.append((args, kwargs)))

    def _fake_create_async_engine(url, **kwargs):
        # 事件机制与方言无关：用 sqlite 内存引擎替代 MySQL（aiomysql 专属的 connect_args/池参数需剥离）
        kwargs.pop("connect_args", None)
        for pool_arg in ("pool_size", "max_overflow", "pool_timeout", "pool_recycle", "pool_pre_ping", "echo"):
            kwargs.pop(pool_arg, None)
        return real_create_async_engine("sqlite+aiosqlite:///:memory:", **kwargs)

    monkeypatch.setattr(mc, "create_async_engine", _fake_create_async_engine)

    config = mc.MySQLConfig(
        settings=MySQLConnectionSettings(host="localhost", slow_sql_threshold_seconds=0.0, slow_sql_critical_seconds=100.0)
    )
    await config._ensure_engine()
    try:
        async with config.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await config.close()

    assert recorded, "慢 SQL 事件未触发 record_slow_sql"
    args, kwargs = recorded[0]
    assert args[0] == "default"  # datasource
    assert args[1] >= 0.0  # duration
    assert kwargs["severity"] == "warning"
    assert kwargs["alert_level"] == "P2"
