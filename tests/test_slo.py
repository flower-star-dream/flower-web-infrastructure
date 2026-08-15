"""
SLO 与错误预算单元测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证 SLO 注册、record 后 evaluate 计算（构造已知失败率场景断言 remaining_ratio）、
              预算耗尽判断、未知 SLO 返回空态、默认/显式错误预算时长（规范 §18.6 / AI-11）。
"""
import pytest

from web_infra.monitoring.slo import (
    DEFAULT_WINDOW_SECONDS,
    ErrorBudgetTracker,
    SloConfig,
)


def test_register_and_evaluate_known_failure_rate():
    """已知失败率场景：剩余比例 = 1 - 误差率/允许误差率"""
    tracker = ErrorBudgetTracker()
    tracker.register(SloConfig(name="chat_api", target_availability=0.90))  # 允许错误率 10%
    for _ in range(95):
        tracker.record_success("chat_api")
    for _ in range(5):
        tracker.record_failure("chat_api")

    budget = tracker.evaluate("chat_api")
    assert budget is not None
    assert budget.name == "chat_api"
    # error_ratio = 5/100 = 0.05；consumed_ratio = 0.05/0.10 = 0.5；remaining_ratio = 0.5
    assert budget.remaining_ratio == 0.5
    assert budget.remaining_percent() == 50.0
    assert budget.total_budget == pytest.approx(DEFAULT_WINDOW_SECONDS * 0.10)
    assert budget.consumed == pytest.approx(budget.total_budget * 0.5)
    assert budget.remaining == pytest.approx(budget.total_budget * 0.5)


def test_budget_exhausted_at_allowed_limit():
    """错误率达到允许上限（误差率 == 允许误差率）时预算耗尽"""
    tracker = ErrorBudgetTracker()
    tracker.register(SloConfig(name="chat_api", target_availability=0.90))
    for _ in range(90):
        tracker.record_success("chat_api")
    for _ in range(10):
        tracker.record_failure("chat_api")

    budget = tracker.evaluate("chat_api")
    assert budget is not None
    assert budget.remaining_ratio == 0.0
    assert budget.remaining == 0.0
    assert tracker.budget_exhausted("chat_api") is True


def test_budget_not_exhausted_below_allowed_limit():
    """错误率低于允许上限时预算未耗尽"""
    tracker = ErrorBudgetTracker()
    tracker.register(SloConfig(name="chat_api", target_availability=0.90))
    for _ in range(91):
        tracker.record_success("chat_api")
    for _ in range(9):
        tracker.record_failure("chat_api")

    budget = tracker.evaluate("chat_api")
    assert budget is not None
    # error_ratio = 0.09；consumed_ratio = 0.9；remaining_ratio = 0.1
    assert budget.remaining_ratio == 0.1
    assert tracker.budget_exhausted("chat_api") is False


def test_unknown_slo_returns_none():
    """未注册 SLO：evaluate 返回 None、budget_exhausted 返回 False、record 静默忽略"""
    tracker = ErrorBudgetTracker()
    tracker.register(SloConfig(name="chat_api", target_availability=0.99))
    tracker.record_failure("not_registered")  # 静默忽略，不抛异常
    tracker.record_success("not_registered")

    assert tracker.evaluate("not_registered") is None
    assert tracker.budget_exhausted("not_registered") is False
    # 已注册 SLO 不受未注册埋点影响
    assert tracker.evaluate("chat_api") is not None


def test_default_error_budget_seconds():
    """默认错误预算时长：窗口 × (1 - 目标可用性)"""
    config = SloConfig(name="embedding_api", target_availability=0.99)
    assert config.effective_error_budget_seconds() == pytest.approx(DEFAULT_WINDOW_SECONDS * 0.01)


def test_explicit_error_budget_seconds_priority():
    """显式错误预算时长优先于窗口换算"""
    tracker = ErrorBudgetTracker()
    tracker.register(
        SloConfig(name="embedding_api", target_availability=0.99, error_budget_seconds=3600.0)
    )
    tracker.record_failure("embedding_api")

    budget = tracker.evaluate("embedding_api")
    assert budget is not None
    assert budget.total_budget == 3600.0


def test_success_only_budget_full():
    """全部成功时预算剩余 100%"""
    tracker = ErrorBudgetTracker()
    tracker.register(SloConfig(name="chat_api", target_availability=0.99))
    for _ in range(10):
        tracker.record_success("chat_api")

    budget = tracker.evaluate("chat_api")
    assert budget is not None
    assert budget.remaining_ratio == 1.0
    assert budget.consumed == 0.0
    assert tracker.budget_exhausted("chat_api") is False


def test_reegister_resets_counters():
    """同名重复注册覆盖配置并清零计数"""
    tracker = ErrorBudgetTracker()
    tracker.register(SloConfig(name="chat_api", target_availability=0.99))
    tracker.record_failure("chat_api")
    tracker.register(SloConfig(name="chat_api", target_availability=0.90))

    budget = tracker.evaluate("chat_api")
    assert budget is not None
    assert budget.remaining_ratio == 1.0  # 计数已清零


def test_perfect_availability_any_failure_exhausts():
    """目标可用性 100%：任一失败即预算耗尽（避免除零）"""
    tracker = ErrorBudgetTracker()
    tracker.register(SloConfig(name="critical_api", target_availability=1.0))
    tracker.record_failure("critical_api")

    budget = tracker.evaluate("critical_api")
    assert budget is not None
    assert budget.remaining_ratio == 0.0
    assert tracker.budget_exhausted("critical_api") is True
