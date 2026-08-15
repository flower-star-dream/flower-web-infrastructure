"""
长事务监控单元测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证规范 §10.4 长事务审计：orm_session 提交路径统计事务耗时，超过阈值
              （构造参数可配，mock 为 0 恒触发）记录 warning 日志（含 datasource 与耗时）
              并递增 db_long_transaction_total 指标；未超阈值不告警；回滚路径不统计。
"""
import logging

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from web_infra.db.mysql_database import DB_LONG_TRANSACTION_TOTAL, MySQLDatabase


def _metric_value(datasource: str = "default") -> int:
    """读取长事务计数指标当前值（指标注册失败时为 0）"""
    if DB_LONG_TRANSACTION_TOTAL is None:
        return 0
    return int(DB_LONG_TRANSACTION_TOTAL.labels(datasource)._value.get())


def _build_db(tmp_path: object, threshold: float) -> MySQLDatabase:
    """构造基于 sqlite+aiosqlite 的最小 MySQLDatabase（复用 test_database.py 的 FakeConfig 模式）"""
    url = f"sqlite+aiosqlite:///{tmp_path.as_posix()}/long_tx.db"
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class _FakeConfig:
        """仅提供 new_session 与 datasource_name 的最小配置替身"""

        datasource_name = "order-db"

        async def new_session(self):
            return factory()

    return MySQLDatabase(_FakeConfig(), long_transaction_threshold_seconds=threshold)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_long_transaction_warns_above_threshold(tmp_path, caplog):
    """事务耗时超过阈值：记录 warning 审计日志（含 datasource）并递增指标"""
    db = _build_db(tmp_path, threshold=0.0)  # 阈值 0 恒触发，验证审计链路
    before = _metric_value("order-db")
    with caplog.at_level(logging.WARNING, logger="web_infra.db.mysql"):
        async with db.orm_session() as session:
            await session.execute(text("SELECT 1"))
    assert any("mysql_long_transaction" in r.message for r in caplog.records)
    assert "order-db" in caplog.text
    assert _metric_value("order-db") == before + 1


@pytest.mark.asyncio
async def test_long_transaction_not_warned_below_threshold(tmp_path, caplog):
    """事务耗时未超过阈值：不告警、不递增指标"""
    db = _build_db(tmp_path, threshold=3600.0)  # 阈值足够大，正常事务不触发
    before = _metric_value("order-db")
    with caplog.at_level(logging.WARNING, logger="web_infra.db.mysql"):
        async with db.orm_session() as session:
            await session.execute(text("SELECT 1"))
    assert not any("mysql_long_transaction" in r.message for r in caplog.records)
    assert _metric_value("order-db") == before


@pytest.mark.asyncio
async def test_long_transaction_rollback_path_not_counted(tmp_path):
    """回滚路径不统计长事务（规范 §10.4：仅 commit 路径审计）"""
    db = _build_db(tmp_path, threshold=0.0)
    before = _metric_value("order-db")
    with pytest.raises(RuntimeError):
        async with db.orm_session() as session:
            await session.execute(text("SELECT 1"))
            raise RuntimeError("boom")
    assert _metric_value("order-db") == before
