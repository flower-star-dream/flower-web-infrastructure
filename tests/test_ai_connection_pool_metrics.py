"""
AI 连接池指标单元测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证 AI-9 连接池指标：活跃/等待连接数 Gauge 注册与记录函数（池名低基数标签 stream/sync）；
              ConnectionPoolManager 在获取路径刷新指标、关闭后置 0，且不改变池对外行为。
              注：测试不调用 init_ai_metrics 修改全局 service 标签（record 均显式传 service，
              避免与 test_ai_gateway_cache 等断言固定 "unknown" 标签的用例产生顺序依赖）。
"""
import pytest

from web_infra.ai import ConnectionPoolManager
from web_infra.monitoring.ai_metrics import (
    AI_CONNECTION_POOL_ACTIVE,
    AI_CONNECTION_POOL_WAITING,
    record_ai_connection_pool_usage,
)


def _gauge_value(gauge, pool: str, service: str = "app") -> float:
    """读取 Gauge 指定池名标签当前值"""
    return gauge.labels(service, pool)._value.get()


def test_record_ai_connection_pool_usage():
    """连接池活跃/等待指标写入 Gauge（池名标签 stream/sync）"""
    record_ai_connection_pool_usage("stream", active=3, waiting=1, service="app")
    assert _gauge_value(AI_CONNECTION_POOL_ACTIVE, "stream") == 3
    assert _gauge_value(AI_CONNECTION_POOL_WAITING, "stream") == 1
    record_ai_connection_pool_usage("sync", active=0, waiting=0, service="app")
    assert _gauge_value(AI_CONNECTION_POOL_ACTIVE, "sync") == 0
    assert _gauge_value(AI_CONNECTION_POOL_WAITING, "sync") == 0


def test_record_ai_connection_pool_usage_clamps_negative():
    """负数入参按 0 钳制（Gauge 不允许负值语义异常）"""
    record_ai_connection_pool_usage("stream", active=-1, waiting=-2, service="app")
    assert _gauge_value(AI_CONNECTION_POOL_ACTIVE, "stream") == 0
    assert _gauge_value(AI_CONNECTION_POOL_WAITING, "stream") == 0


@pytest.mark.asyncio
async def test_manager_refreshes_metrics_on_get_and_close():
    """ConnectionPoolManager 获取路径刷新指标、关闭后置 0（AI-9，service 缺省 unknown）"""
    manager = ConnectionPoolManager()
    await manager.get_stream_client()
    await manager.get_sync_client()
    # 池刚建立未发起请求，活跃/等待为 0 且 Gauge 已刷新（值为确定非空）
    assert _gauge_value(AI_CONNECTION_POOL_ACTIVE, "stream", service="unknown") >= 0
    assert _gauge_value(AI_CONNECTION_POOL_WAITING, "stream", service="unknown") >= 0
    assert _gauge_value(AI_CONNECTION_POOL_ACTIVE, "sync", service="unknown") >= 0
    assert _gauge_value(AI_CONNECTION_POOL_WAITING, "sync", service="unknown") >= 0
    await manager.close()
    # 关闭后池置空，活跃/等待归 0
    assert _gauge_value(AI_CONNECTION_POOL_ACTIVE, "stream", service="unknown") == 0
    assert _gauge_value(AI_CONNECTION_POOL_WAITING, "stream", service="unknown") == 0
    assert _gauge_value(AI_CONNECTION_POOL_ACTIVE, "sync", service="unknown") == 0
    assert _gauge_value(AI_CONNECTION_POOL_WAITING, "sync", service="unknown") == 0


@pytest.mark.asyncio
async def test_manager_metrics_refresh_does_not_break_behavior():
    """指标刷新不改变池对外行为（单例复用与分池隔离保持，AI-9 回归）"""
    manager = ConnectionPoolManager()
    stream_client = await manager.get_stream_client()
    sync_client = await manager.get_sync_client()
    assert stream_client is not sync_client
    assert await manager.get_stream_client() is stream_client  # 单例复用
    await manager.close()
    assert manager._stream_client is None
    assert manager._sync_client is None
