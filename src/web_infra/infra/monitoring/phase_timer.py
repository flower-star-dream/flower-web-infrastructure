"""
全链路分阶段耗时埋点

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 按规范 §18.5.1 实现全链路分阶段耗时埋点（gateway/auth/biz/db/rpc），关联 TraceId 输出各段耗时。
"""
from __future__ import annotations

import time
from contextvars import ContextVar

from web_infra.infra.monitoring.metrics import REQUEST_PHASE_DURATION_SECONDS, _service

_PHASE_TIMER_VAR: ContextVar["PhaseTimer | None"] = ContextVar("phase_timer", default=None)

_PHASE_ORDER = ("gateway", "auth", "biz", "db", "rpc", "total")


class PhaseTimer:
    """请求分阶段耗时埋点器"""

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self._phases: dict[str, float] = {}

    @classmethod
    def start(cls) -> "PhaseTimer":
        """创建并绑定当前请求的 PhaseTimer"""
        timer = cls()
        _PHASE_TIMER_VAR.set(timer)
        return timer

    @classmethod
    def mark(cls, phase: str) -> None:
        """标记阶段完成（无请求上下文时静默跳过）"""
        timer = _PHASE_TIMER_VAR.get()
        if timer is None:
            return
        timer._phases[phase] = (time.perf_counter() - timer._start) * 1000

    def mark_total(self) -> None:
        """标记请求总耗时"""
        self._phases["total"] = (time.perf_counter() - self._start) * 1000

    @classmethod
    def clear(cls) -> None:
        """清理请求上下文（防止串扰）"""
        _PHASE_TIMER_VAR.set(None)

    def to_log_fields(self) -> dict[str, float]:
        """生成阶段耗时日志字段"""
        return {f"phase_{name}_ms": round(value, 3) for name, value in self._phases.items()}

    def record_metrics(self, service: str | None = None) -> None:
        """将各阶段耗时写入指标（按阶段顺序计算增量）"""
        service = service or _service()
        prev_ms = 0.0
        for phase in _PHASE_ORDER:
            elapsed_ms = self._phases.get(phase)
            if elapsed_ms is None:
                continue
            delta_ms = max(elapsed_ms - prev_ms, 0.0)
            REQUEST_PHASE_DURATION_SECONDS.labels(service, phase).observe(delta_ms / 1000.0)
            prev_ms = elapsed_ms
