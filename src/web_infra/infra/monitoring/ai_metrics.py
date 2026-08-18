"""
AI 模型调用指标（prometheus-client）

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 按 AI 规范 §15 采集模型调用核心指标：QPS/错误率（calls）、TTFT/全量时延（P50/P95/P99）、
              Token 用量、成本、缓存命中与降级次数。标签禁用高基数动态值（模型名/供应商为低基数允许，
              用户 ID/完整 Prompt 不进标签）。由 ModelGateway 与 AICache 埋点。
              另按 AI-9 采集 AI 连接池活跃/等待连接数（ai_connection_pool_active / ai_connection_pool_waiting，
              池名低基数标签：stream/sync），供 /metrics 抓取；池满告警联动熔断/限流由上层接入。

SLO 接入说明（规范 §18.6 / AI-11，仅注释示例，不改变本模块行为）：
  本模块只采集指标；量化 SLO 与错误预算计算由 monitoring/slo.py 的 ErrorBudgetTracker 承接，
  调用方在 ModelGateway 埋点处同步驱动 SLO 计数，例如：
    tracker.register(SloConfig(name="chat_api", target_availability=0.99))
    record_ai_call(model, "success" if ok else "error")
    tracker.record_success("chat_api") if ok else tracker.record_failure("chat_api")
    if tracker.budget_exhausted("chat_api"): ...   # 触发告警/熔断
  TTFT P95 可经 AI_LLM_TTFT_SECONDS Histogram 分位数推导，与错误预算共同构成 SLO 面板。
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

_service_name = "unknown"

# AI 时延桶：TTFT 关注首包（亚秒级），全量生成关注长尾
AI_TTFT_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
AI_DURATION_BUCKETS = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)


def init_ai_metrics(service_name: str) -> None:
    """初始化 AI 指标服务名标签（全局覆盖，幂等）"""
    global _service_name
    if service_name:
        _service_name = service_name


def _service() -> str:
    """返回当前服务名"""
    return _service_name


# 调用量（outcome：success/error/degraded/cache_hit/cache_miss，低基数）
AI_LLM_CALLS_TOTAL = Counter("ai_llm_calls_total", "AI 模型调用总数", ["service", "model", "outcome"])
# 时延（P50/P95/P99 由 Histogram 分位数推导）
AI_LLM_TTFT_SECONDS = Histogram("ai_llm_ttft_seconds", "AI 模型首 Token 时延分布", ["service", "model"], buckets=AI_TTFT_BUCKETS)
AI_LLM_DURATION_SECONDS = Histogram("ai_llm_duration_seconds", "AI 模型全量生成时延分布", ["service", "model"], buckets=AI_DURATION_BUCKETS)
# Token 用量与成本
AI_TOKEN_TOTAL = Counter("ai_token_total", "AI Token 用量", ["service", "model", "type"])
AI_COST_TOTAL = Counter("ai_cost_total", "AI 调用成本（元）", ["service", "model"])
# AI 连接池运行指标（AI-9：活跃/等待连接数，池名低基数标签 stream/sync；
# 池满告警联动熔断/限流由上层接入，本模块只负责采集）
AI_CONNECTION_POOL_ACTIVE = Gauge("ai_connection_pool_active", "AI 连接池活跃连接数", ["service", "pool"])
AI_CONNECTION_POOL_WAITING = Gauge("ai_connection_pool_waiting", "AI 连接池等待连接数", ["service", "pool"])


def record_ai_call(model: str, outcome: str, service: str | None = None) -> None:
    """记录一次模型调用（outcome：success/error/degraded/cache_hit/cache_miss）"""
    AI_LLM_CALLS_TOTAL.labels(service or _service(), model, outcome).inc()


def record_ai_ttft(model: str, seconds: float, service: str | None = None) -> None:
    """记录首 Token 时延（TTFT）"""
    AI_LLM_TTFT_SECONDS.labels(service or _service(), model).observe(seconds)


def record_ai_duration(model: str, seconds: float, service: str | None = None) -> None:
    """记录全量生成时延"""
    AI_LLM_DURATION_SECONDS.labels(service or _service(), model).observe(seconds)


def record_ai_tokens(model: str, prompt_tokens: int, completion_tokens: int, service: str | None = None) -> None:
    """记录 Token 用量（输入/输出分型）"""
    labels_service = service or _service()
    AI_TOKEN_TOTAL.labels(labels_service, model, "prompt").inc(prompt_tokens)
    AI_TOKEN_TOTAL.labels(labels_service, model, "completion").inc(completion_tokens)


def record_ai_cost(model: str, cost: float, service: str | None = None) -> None:
    """记录调用成本（元）"""
    AI_COST_TOTAL.labels(service or _service(), model).inc(cost)


def record_ai_connection_pool_usage(pool: str, active: int, waiting: int, service: str | None = None) -> None:
    """记录 AI 连接池活跃/等待连接数（AI-9，池名低基数：stream/sync）。

    活跃 = 池内已建连接数（含处理中），等待 = 尚未分配到连接的排队请求数；
    由 ConnectionPoolManager 在池获取路径 / /metrics 抓取前刷新，池未建立时置 0。
    """
    labels_service = service or _service()
    AI_CONNECTION_POOL_ACTIVE.labels(labels_service, pool).set(max(int(active), 0))
    AI_CONNECTION_POOL_WAITING.labels(labels_service, pool).set(max(int(waiting), 0))
