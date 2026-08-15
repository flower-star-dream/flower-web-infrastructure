"""
AI 指标单元测试

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 验证 AI 调用/时延/Token/成本指标埋点与标签低基数（AI 规范 §15）。
"""
from web_infra.monitoring import (
    init_ai_metrics,
    record_ai_call,
    record_ai_cost,
    record_ai_duration,
    record_ai_tokens,
    record_ai_ttft,
)
from web_infra.monitoring.ai_metrics import (
    AI_COST_TOTAL,
    AI_LLM_CALLS_TOTAL,
    AI_LLM_DURATION_SECONDS,
    AI_LLM_TTFT_SECONDS,
    AI_TOKEN_TOTAL,
)


def _metric_value(counter, *labels) -> float:
    """读取 Counter 指定标签的累计值"""
    return counter.labels(*labels)._value.get()


def test_record_ai_call_labels():
    """调用指标：低基数标签（service/model/outcome）"""
    init_ai_metrics("app")
    before = _metric_value(AI_LLM_CALLS_TOTAL, "app", "deepseek", "success")
    record_ai_call("deepseek", "success")
    record_ai_call("deepseek", "degraded")
    after = _metric_value(AI_LLM_CALLS_TOTAL, "app", "deepseek", "success")
    assert after == before + 1
    assert _metric_value(AI_LLM_CALLS_TOTAL, "app", "deepseek", "degraded") >= 1


def test_record_ai_ttft_and_duration():
    """TTFT 与全量时延写入 Histogram"""
    init_ai_metrics("app")
    record_ai_ttft("deepseek", 0.5)
    record_ai_duration("deepseek", 3.2)
    assert AI_LLM_TTFT_SECONDS.labels("app", "deepseek")._sum.get() > 0
    assert AI_LLM_DURATION_SECONDS.labels("app", "deepseek")._sum.get() > 0


def test_record_ai_tokens_by_type():
    """Token 用量分型（prompt/completion）"""
    before = _metric_value(AI_TOKEN_TOTAL, "app", "deepseek", "prompt")
    record_ai_tokens("deepseek", prompt_tokens=100, completion_tokens=50)
    assert _metric_value(AI_TOKEN_TOTAL, "app", "deepseek", "prompt") == before + 100
    assert _metric_value(AI_TOKEN_TOTAL, "app", "deepseek", "completion") >= 50


def test_record_ai_cost():
    """成本指标累计"""
    before = _metric_value(AI_COST_TOTAL, "app", "deepseek")
    record_ai_cost("deepseek", 0.5)
    assert _metric_value(AI_COST_TOTAL, "app", "deepseek") == before + 0.5
