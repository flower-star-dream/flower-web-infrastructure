"""
模型网关连接池单元测试

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 验证流式/非流式分池隔离、单例复用与 close 释放（AI 规范 §5.1）。
"""
import pytest

from web_infra.ai import ConnectionPoolManager


@pytest.mark.asyncio
async def test_stream_and_sync_clients_isolated():
    """流式与非流式客户端分池隔离（不同实例）"""
    manager = ConnectionPoolManager()
    stream_client = await manager.get_stream_client()
    sync_client = await manager.get_sync_client()
    assert stream_client is not sync_client
    await manager.close()


@pytest.mark.asyncio
async def test_clients_singleton():
    """同一类型客户端单例复用"""
    manager = ConnectionPoolManager()
    assert await manager.get_stream_client() is await manager.get_stream_client()
    assert await manager.get_sync_client() is await manager.get_sync_client()
    await manager.close()


@pytest.mark.asyncio
async def test_close_releases_clients():
    """close 后客户端置空"""
    manager = ConnectionPoolManager()
    await manager.get_stream_client()
    await manager.get_sync_client()
    await manager.close()
    assert manager._stream_client is None
    assert manager._sync_client is None


@pytest.mark.asyncio
async def test_pool_limits_split():
    """分池上限：流式池上限须小于非流式池（AI 规范 §5.1）"""
    manager = ConnectionPoolManager()
    assert manager._config.stream_max_connections < manager._config.sync_max_connections
    await manager.close()
