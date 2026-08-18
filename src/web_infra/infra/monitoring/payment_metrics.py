"""
支付指标与告警埋点

@Author: 花海
@Date: 2026/08/16
@Description: 支付核心指标（规范 §11.1）：下单成功率/失败率、回调处理成功率与延迟、
              退款成功率/失败率、渠道调用结果、冲正计数。指标标签低基数（渠道/结果分类），
              供 /metrics 采集与分级告警（对账差异等 P0 告警联动由上层接入）。
"""
from __future__ import annotations

from prometheus_client import Counter, Histogram

# 指标重复注册兜底（多进程/单测重复导入场景，监控不阻断业务主链路）
try:
    PAY_PREPAY_TOTAL = Counter(
        "pay_prepay_total", "支付下单结果（规范 §11.1 下单成功率）", ["channel", "outcome"]
    )
    PAY_CALLBACK_TOTAL = Counter(
        "pay_callback_total", "支付回调处理结果（success/verify_failed/biz_error）", ["channel", "outcome"]
    )
    PAY_CALLBACK_DURATION_SECONDS = Histogram(
        "pay_callback_duration_seconds", "回调处理耗时分布（回调链路须毫秒级，§2.3）", ["channel"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )
    PAY_REFUND_TOTAL = Counter(
        "pay_refund_total", "退款申请/终态结果（§5.3/§7.6）", ["channel", "outcome"]
    )
    PAY_CHANNEL_CALL_TOTAL = Counter(
        "pay_channel_call_total", "渠道调用结果（success/error）", ["channel", "method", "outcome"]
    )
    PAY_REVERSAL_TOTAL = Counter(
        "pay_reversal_total", "冲正动作计数（§7.5，异常激增 P0 告警）", ["channel"]
    )
    PAY_CLOSE_TOTAL = Counter(
        "pay_close_total", "超时关单任务结果（§5.5/§11.1，closed/skipped）", ["channel", "outcome"]
    )
    PAY_QUERY_FALLBACK_TOTAL = Counter(
        "pay_query_fallback_total", "查单兜底次数（§7.4/§11.1：结果未知/掉单补偿经查单收敛）", ["channel", "outcome"]
    )
except Exception:  # pragma: no cover - 指标重复注册等异常兜底
    PAY_PREPAY_TOTAL = PAY_CALLBACK_TOTAL = PAY_CALLBACK_DURATION_SECONDS = None
    PAY_REFUND_TOTAL = PAY_CHANNEL_CALL_TOTAL = PAY_REVERSAL_TOTAL = None
    PAY_CLOSE_TOTAL = PAY_QUERY_FALLBACK_TOTAL = None


def _inc(counter, *labels) -> None:
    """计数兜底（指标未注册时静默，不阻断业务主链路）"""
    if counter is not None:
        counter.labels(*labels).inc()


def record_prepay(channel: str, success: bool) -> None:
    """下单结果埋点（§11.1 下单成功率）"""
    _inc(PAY_PREPAY_TOTAL, channel, "success" if success else "error")


def record_callback(channel: str, outcome: str, duration_seconds: float | None = None) -> None:
    """回调处理结果埋点（§11.1 回调成功率；outcome: success/verify_failed/biz_error）"""
    _inc(PAY_CALLBACK_TOTAL, channel, outcome)
    if duration_seconds is not None and PAY_CALLBACK_DURATION_SECONDS is not None:
        PAY_CALLBACK_DURATION_SECONDS.labels(channel).observe(duration_seconds)


def record_refund(channel: str, outcome: str) -> None:
    """退款结果埋点（§11.1 退款成功率；outcome: success/error）"""
    _inc(PAY_REFUND_TOTAL, channel, outcome)


def record_channel_call(channel: str, method: str, success: bool) -> None:
    """渠道调用结果埋点（§11.1 渠道调用错误率）"""
    _inc(PAY_CHANNEL_CALL_TOTAL, channel, method, "success" if success else "error")


def record_reversal(channel: str) -> None:
    """冲正动作埋点（§7.5，异常激增 P0 告警）"""
    _inc(PAY_REVERSAL_TOTAL, channel)


def record_close(channel: str, outcome: str) -> None:
    """关单任务结果埋点（§5.5/§11.1 关单成功率；outcome: closed/skipped）"""
    _inc(PAY_CLOSE_TOTAL, channel, outcome)


def record_query_fallback(channel: str, outcome: str) -> None:
    """查单兜底埋点（§7.4/§11.1 查单兜底率；outcome: success/not_found/error）"""
    _inc(PAY_QUERY_FALLBACK_TOTAL, channel, outcome)
