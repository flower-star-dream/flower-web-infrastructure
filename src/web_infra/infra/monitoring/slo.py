"""
SLO 与错误预算模块（可量化服务水平目标）

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 按规范 §18.6（S18-6：核心接口定义可量化 SLO 与错误预算机制）与
              AI 扩展 §AI-11（定义量化 SLO——TTFT P95、错误率——与错误预算）提供：
              SLO 配置（目标可用性）、错误预算计算（以 30 天窗口按错误率换算预算消耗）
              与预算耗尽判断。单实例内存实现，供指标计算/告警判断调用；
              进程内状态，多实例部署建议接入共享存储汇总后统一评估。
              用法示例：
                tracker = ErrorBudgetTracker()
                tracker.register(SloConfig(name="chat_api", target_availability=0.99))
                tracker.record_failure("chat_api")   # 业务失败路径埋点
                budget = tracker.evaluate("chat_api")
                if tracker.budget_exhausted("chat_api"):
                    ...  # 触发告警/熔断开关
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

# 默认评估窗口：30 天（秒），对应规范「月度错误预算」口径
DEFAULT_WINDOW_SECONDS = 30 * 24 * 3600


@dataclass(frozen=True)
class SloConfig:
    """SLO 配置（对应规范 §18.6：核心接口可量化 SLO 定义）

    :param name: SLO 名称（低基数标签，如 chat_api / embedding_api）
    :param target_availability: 目标可用性（0.99 = 99%）
    :param error_budget_seconds: 显式错误预算时长（秒）；None 时按窗口自动换算
    :param window_seconds: 评估窗口（秒），默认 30 天
    """

    name: str
    target_availability: float = 0.99
    error_budget_seconds: float | None = None
    window_seconds: float = DEFAULT_WINDOW_SECONDS

    def effective_error_budget_seconds(self) -> float:
        """生效的错误预算时长（秒）：显式配置优先，否则按 窗口 × (1 - 目标可用性) 换算"""
        if self.error_budget_seconds is not None:
            return self.error_budget_seconds
        return self.window_seconds * (1.0 - self.target_availability)


@dataclass(frozen=True)
class ErrorBudget:
    """错误预算计算结果（不可变快照，供指标导出/告警判断读取）

    :param name: SLO 名称
    :param total_budget: 总预算（秒）
    :param consumed: 已消耗预算（秒）
    :param remaining: 剩余预算（秒）
    :param remaining_ratio: 剩余比例（0~1；0 表示预算耗尽）
    """

    name: str
    total_budget: float
    consumed: float
    remaining: float
    remaining_ratio: float

    def remaining_percent(self) -> float:
        """剩余预算百分比（0~100，remaining_ratio 的百分数形式，用于告警阈值对比）"""
        return round(self.remaining_ratio * 100.0, 2)


class ErrorBudgetTracker:
    """SLO 注册与错误预算追踪器（@Stateful：进程内内存状态，多实例建议共享存储汇总）

    以「错误率 vs 允许错误率」口径换算预算消耗：误差率 与 (1 - target_availability) 的比值
    即消耗比例，避免对单次失败时长建模（简化实现，可观测且可测）。
    未注册的 SLO：record 静默忽略（监控组件不阻断业务主链路），evaluate/budget_exhausted 返回空态。
    """

    def __init__(self) -> None:
        """初始化追踪器（空 SLO 表，线程安全）"""
        self._configs: dict[str, SloConfig] = {}
        self._total_requests: dict[str, int] = {}
        self._failures: dict[str, int] = {}
        self._lock = Lock()

    def register(self, config: SloConfig) -> None:
        """注册一个 SLO；同名重复注册覆盖旧配置并清零计数"""
        with self._lock:
            self._configs[config.name] = config
            self._total_requests[config.name] = 0
            self._failures[config.name] = 0

    def record_success(self, name: str) -> None:
        """记录一次成功调用（计入总请求数，不消耗预算）；未注册的 SLO 静默忽略"""
        with self._lock:
            if name not in self._configs:
                return
            self._total_requests[name] += 1

    def record_failure(self, name: str) -> None:
        """记录一次失败调用（计入总请求数与预算消耗）；未注册的 SLO 静默忽略"""
        with self._lock:
            if name not in self._configs:
                return
            self._total_requests[name] += 1
            self._failures[name] += 1

    def evaluate(self, name: str) -> ErrorBudget | None:
        """评估指定 SLO 的当前错误预算；未注册返回 None

        计算口径：error_ratio = failures / max(total_requests, 1)；
        allowed_error_ratio = 1 - target_availability；
        consumed_ratio = min(error_ratio / allowed_error_ratio, 1.0)（封顶 1.0）；
        remaining_ratio = 1 - consumed_ratio；已消耗秒数 = consumed_ratio × 总预算。
        目标可用性 = 100%（允许错误率为 0）时：任一失败即视为预算耗尽。
        """
        with self._lock:
            config = self._configs.get(name)
            if config is None:
                return None
            total = self._total_requests.get(name, 0)
            failures = self._failures.get(name, 0)

        allowed_error_ratio = 1.0 - config.target_availability
        if allowed_error_ratio <= 0:
            consumed_ratio = 1.0 if failures > 0 else 0.0
        else:
            error_ratio = failures / max(total, 1)
            consumed_ratio = min(error_ratio / allowed_error_ratio, 1.0)

        remaining_ratio = 1.0 - consumed_ratio
        total_budget = config.effective_error_budget_seconds()
        consumed = consumed_ratio * total_budget
        remaining = total_budget - consumed
        return ErrorBudget(
            name=name,
            total_budget=total_budget,
            consumed=consumed,
            remaining=remaining,
            remaining_ratio=round(remaining_ratio, 6),
        )

    def budget_exhausted(self, name: str) -> bool:
        """预算是否耗尽（剩余比例 <= 0）；未注册的 SLO 返回 False"""
        budget = self.evaluate(name)
        return budget is not None and budget.remaining_ratio <= 0
