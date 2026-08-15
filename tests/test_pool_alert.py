"""
连接池双条件预警评估模块单元测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证规范 §18.5 双条件预警评估：使用率 ≥80% 且持续 N 分钟才触发告警；
              未达高水位不触发、高水位未持续足够时长不触发、reset 清除历史、
              时间窗口外旧样本不参与判定、连接上限非法时按 0 使用率处理。
"""
import pytest

from web_infra.monitoring.pool_alert import PoolAlertConfig, PoolAlertEvaluator


@pytest.fixture
def clock(monkeypatch):
    """可控单调时钟：驱动时间推进验证持续时长判定"""
    import web_infra.monitoring.pool_alert as pa

    now = [1000.0]

    def _tick(seconds: float) -> None:
        """推进模拟时钟 seconds 秒"""
        now[0] += seconds

    def _monotonic() -> float:
        return now[0]

    monkeypatch.setattr(pa.time, "monotonic", _monotonic)
    return _tick


def test_dual_condition_triggered_after_sustain(clock):
    """双条件触发：使用率 ≥80% 且持续 ≥5 分钟才告警；持续不足不告警"""
    evaluator = PoolAlertEvaluator()
    evaluator.report_usage("order-db", used=90, total=100)  # 90% 高水位
    clock(4 * 60)  # 持续 4 分钟
    evaluator.report_usage("order-db", used=95, total=100)
    assert evaluator.evaluate() == []  # 持续不足 5 分钟

    clock(2 * 60)  # 共持续 6 分钟
    evaluator.report_usage("order-db", used=95, total=100)
    assert evaluator.evaluate() == ["order-db"]


def test_not_triggered_when_usage_below_threshold(clock):
    """第一条件不满足：使用率始终低于 80% 不告警"""
    evaluator = PoolAlertEvaluator()
    evaluator.report_usage("order-db", used=50, total=100)
    clock(10 * 60)
    evaluator.report_usage("order-db", used=70, total=100)  # 70% < 80%
    assert evaluator.evaluate() == []


def test_not_triggered_when_recovered_below_threshold(clock):
    """恢复场景：高水位回落到阈值以下后再次高水位，从回落点重新起算持续时长"""
    evaluator = PoolAlertEvaluator()
    evaluator.report_usage("order-db", used=90, total=100)
    clock(5 * 60)
    evaluator.report_usage("order-db", used=60, total=100)  # 回落到 60%
    clock(1 * 60)
    evaluator.report_usage("order-db", used=90, total=100)  # 再次高水位，仅持续 1 分钟
    assert evaluator.evaluate() == []


def test_reset_clears_history(clock):
    """reset：清除指定池历史后不再告警，其他池不受影响（池关闭/重建场景）"""
    evaluator = PoolAlertEvaluator()
    evaluator.report_usage("order-db", used=90, total=100)
    clock(10 * 60)
    evaluator.report_usage("order-db", used=95, total=100)
    evaluator.reset("order-db")
    assert evaluator.evaluate() == []

    evaluator.report_usage("user-db", used=90, total=100)
    clock(10 * 60)
    evaluator.report_usage("user-db", used=95, total=100)
    assert evaluator.evaluate() == ["user-db"]


def test_history_window_excludes_stale_samples(clock):
    """有界历史：窗口外旧样本不参与判定，持续时长仅按窗口内样本估算"""
    evaluator = PoolAlertEvaluator(
        config=PoolAlertConfig(sustain_minutes=5),
        history_window_seconds=600.0,  # 最近 10 分钟窗口
    )
    evaluator.report_usage("order-db", used=90, total=100)
    clock(15 * 60)  # 15 分钟后（超出窗口），旧样本失效
    evaluator.report_usage("order-db", used=90, total=100)
    assert evaluator.evaluate() == []  # 窗口内仅最新样本，持续时长不足

    clock(5 * 60 + 1)  # 窗口内连续高水位 5 分钟以上
    evaluator.report_usage("order-db", used=95, total=100)
    assert evaluator.evaluate() == ["order-db"]


def test_usage_ratio_zero_when_total_invalid(clock):
    """连接上限非法（<=0）时按 0 使用率处理，不触发高水位"""
    evaluator = PoolAlertEvaluator()
    evaluator.report_usage("order-db", used=100, total=0)
    clock(10 * 60)
    evaluator.report_usage("order-db", used=100, total=-1)
    assert evaluator.evaluate() == []


def test_custom_config_threshold():
    """自定义配置：高水位阈值与持续时长可配（85% 使用率低于 90% 阈值不告警）"""
    evaluator = PoolAlertEvaluator(config=PoolAlertConfig(high_usage_ratio=0.9, sustain_minutes=1))
    evaluator.report_usage("order-db", used=85, total=100)
    assert evaluator.evaluate() == []
