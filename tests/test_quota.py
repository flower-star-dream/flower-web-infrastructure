"""
配额管理单元测试

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 验证调用次数/Token/成本三型配额、窗口重置与超限错误码（AI 规范 §5.3/§6.2）。
"""
import pytest

from web_infra.capabilities.ai import QuotaConfig, QuotaManager
from web_infra.infra.error import BizException


@pytest.mark.asyncio
async def test_call_quota_exceeded():
    """调用次数超限抛 E1-RATE-000"""
    manager = QuotaManager(default_config=QuotaConfig(max_calls=2, window_seconds=3600))
    await manager.check_and_consume("tenant", "t1")
    await manager.check_and_consume("tenant", "t1")
    with pytest.raises(BizException) as exc_info:
        await manager.check_and_consume("tenant", "t1")
    assert exc_info.value.code == "E1-RATE-000"


@pytest.mark.asyncio
async def test_token_quota_exceeded():
    """Token 配额超限抛 E1-RATE-000"""
    manager = QuotaManager(default_config=QuotaConfig(max_tokens=100, window_seconds=3600))
    await manager.check_and_consume("tenant", "t1", tokens=60)
    await manager.check_and_consume("tenant", "t1", tokens=40)
    with pytest.raises(BizException):
        await manager.check_and_consume("tenant", "t1", tokens=10)


@pytest.mark.asyncio
async def test_cost_quota_exceeded():
    """成本预算超限抛 E4-AI-005"""
    manager = QuotaManager(default_config=QuotaConfig(max_cost=1.0, window_seconds=3600))
    await manager.check_and_consume("tenant", "t1", cost=0.4)
    await manager.check_and_consume("tenant", "t1", cost=0.4)
    with pytest.raises(BizException) as exc_info:
        await manager.check_and_consume("tenant", "t1", cost=0.3)
    assert exc_info.value.code == "E4-AI-005"


@pytest.mark.asyncio
async def test_quota_window_reset():
    """窗口过期后配额重置（新窗口重新计数）"""
    from web_infra.capabilities.ai.quota.in_memory_quota_store import InMemoryQuotaStore

    store = InMemoryQuotaStore()
    manager = QuotaManager(store=store, default_config=QuotaConfig(max_calls=1, window_seconds=3600))
    await manager.check_and_consume("tenant", "t1")
    with pytest.raises(BizException):
        await manager.check_and_consume("tenant", "t1")
    # 模拟窗口过期
    for key in list(store._store):
        counter, _ = store._store[key]
        store._store[key] = (counter, 0.0)  # expire_at 已过
    await manager.check_and_consume("tenant", "t1")  # 新窗口放行


@pytest.mark.asyncio
async def test_scope_isolation():
    """不同租户配额独立"""
    manager = QuotaManager(default_config=QuotaConfig(max_calls=1, window_seconds=3600))
    await manager.check_and_consume("tenant", "t1")
    await manager.check_and_consume("tenant", "t2")  # 其他租户不受影响
    with pytest.raises(BizException):
        await manager.check_and_consume("tenant", "t1")


@pytest.mark.asyncio
async def test_empty_scope_raises():
    """scope/scope_value 为空抛 ValueError"""
    manager = QuotaManager()
    with pytest.raises(ValueError):
        await manager.check_and_consume("", "t1")
    with pytest.raises(ValueError):
        await manager.check_and_consume("tenant", "")
