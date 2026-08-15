"""
Token 计费与成本统计单元测试

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 验证成本计算、按配置计费、持久化钩子与内存聚合（AI 规范 §5.2/§14）。
"""
import asyncio

import pytest

from web_infra.ai import ModelConfig, Usage, UsageAccounting, UsageRecord, UsageRecordStoreInterface


def test_record_cost_calculation():
    """成本 = 输入/输出 Token × 单价（每 1K）"""
    acc = UsageAccounting()
    usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    record = acc.record(usage, "deepseek-chat", input_price_per_1k=1.0, output_price_per_1k=2.0)
    assert record.cost == pytest.approx(1.0 * 1 + 0.5 * 2)  # 1.0 + 1.0 = 2.0
    assert record.total_tokens == 1500


def test_record_total_tokens_fallback():
    """total_tokens 未提供时按输入+输出计算"""
    acc = UsageAccounting()
    usage = Usage(prompt_tokens=300, completion_tokens=200)
    record = acc.record(usage, "m1")
    assert record.total_tokens == 500


def test_record_from_config_uses_prices():
    """按模型配置单价计费"""
    acc = UsageAccounting()
    config = ModelConfig(
        id=1, model_name="deepseek", model_code="deepseek-chat", provider="deepseek",
        api_base="http://x", api_key="k", input_price_per_1k=0.5, output_price_per_1k=1.5,
    )
    usage = Usage(prompt_tokens=2000, completion_tokens=1000)
    record = acc.record_from_config(usage, config, tenant_id="t1", scene="chat")
    assert record.provider == "deepseek"
    assert record.tenant_id == "t1"
    assert record.cost == pytest.approx(2.0 * 0.5 + 1.0 * 1.5)


def test_aggregate_by_model():
    """按模型聚合：Token 与成本累计"""
    acc = UsageAccounting()
    acc.record(Usage(prompt_tokens=1000, completion_tokens=1000), "m1", input_price_per_1k=1.0, output_price_per_1k=1.0)
    acc.record(Usage(prompt_tokens=500, completion_tokens=500), "m1", input_price_per_1k=1.0, output_price_per_1k=1.0)
    acc.record(Usage(prompt_tokens=100, completion_tokens=100), "m2")
    agg = {item["model_code"]: item for item in acc.aggregate(group_by=("model_code",))}
    assert agg["m1"]["calls"] == 2
    assert agg["m1"]["total_tokens"] == 3000
    assert agg["m1"]["cost"] == pytest.approx(2.0 + 1.0)
    assert agg["m2"]["calls"] == 1


def test_aggregate_by_tenant_and_scene():
    """按租户/场景聚合独立分组"""
    acc = UsageAccounting()
    acc.record(Usage(prompt_tokens=100, completion_tokens=100), "m1", tenant_id="t1", scene="chat")
    acc.record(Usage(prompt_tokens=200, completion_tokens=200), "m1", tenant_id="t2", scene="chat")
    tenant_agg = {item["tenant_id"]: item for item in acc.aggregate(group_by=("tenant_id",))}
    assert tenant_agg["t1"]["total_tokens"] == 200
    assert tenant_agg["t2"]["total_tokens"] == 400


@pytest.mark.asyncio
async def test_record_store_hook():
    """配置持久化存储时每条记录写入 store"""
    saved: list[UsageRecord] = []

    class _Store(UsageRecordStoreInterface):
        async def save(self, record: UsageRecord) -> None:
            saved.append(record)

    acc = UsageAccounting(record_store=_Store())
    acc.record(Usage(prompt_tokens=10, completion_tokens=5), "m1")
    # 等待异步持久化任务完成
    for _ in range(50):
        if saved:
            break
        await asyncio.sleep(0.01)
    assert len(saved) == 1
    assert saved[0].model_code == "m1"
