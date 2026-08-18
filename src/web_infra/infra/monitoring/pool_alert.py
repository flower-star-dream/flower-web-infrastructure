"""
连接池双条件预警评估模块

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 按规范 §18.5 实现连接池双条件预警评估：池使用率 ≥ 阈值（默认 80%）且持续 N 分钟
              （默认 5 分钟）时判定触发告警。评估器仅消费采样（report_usage），由调用方按
              check_interval_seconds 建议周期喂入 MySQL / Redis / MongoDB 连接池使用率
              （数据源使用率由 monitoring/pool_metrics 采集）；evaluate() 返回当前应告警的池名列表。
              告警触发后不在此处投递（框架只做判定），由上层接入通知/告警渠道并联动熔断/限流（§18.5）。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class PoolAlertConfig:
    """连接池双条件预警配置（规范 §18.5：使用率 ≥ 阈值 且 持续 N 分钟）"""

    # 使用率阈值（used/total ≥ 该值判定高水位，默认 80%）
    high_usage_ratio: float = 0.8
    # 持续分钟数（高水位持续达到该时长才触发告警，防止瞬时抖动误报）
    sustain_minutes: int = 5
    # 采样建议周期（秒）：调用方按此周期喂入 report_usage（用于估算历史窗口容量）
    check_interval_seconds: float = 60.0


class PoolAlertEvaluator:
    """连接池双条件预警评估器（@Stateful：进程内采样历史，多实例建议各自评估后聚合上报）

    双条件预警：池使用率 ≥ high_usage_ratio（第一条件）且持续 ≥ sustain_minutes（第二条件）。
    历史采样按池名分组保存在有界 deque 中（超出 history_window_seconds 的旧样本在 evaluate 时忽略），
    线程安全（threading.Lock）；池关闭/重建时调用 reset(name) 清除历史，避免旧样本导致误报。
    """

    def __init__(self, config: PoolAlertConfig | None = None, history_window_seconds: float = 600.0) -> None:
        """初始化评估器

        :param config: 双条件预警配置（缺省使用默认 80% / 5 分钟 / 60s）
        :param history_window_seconds: 单池历史采样时间窗口（秒），默认最近 10 分钟
        """
        self._config = config or PoolAlertConfig()
        self._window_seconds = max(history_window_seconds, 1.0)
        # 按池名保存 (monotonic 时间戳, 使用率)；有界 deque 防止历史无限增长
        self._history: dict[str, deque[tuple[float, float]]] = {}
        # S16-2 豁免：临界区为纯内存操作，无 I/O 阻塞，不适用 3s 获取超时
        self._lock = threading.Lock()

    def report_usage(self, name: str, used: int, total: int) -> None:
        """记录一次连接池使用率采样

        :param name: 池名（datasource，低基数标签）
        :param used: 当前已用连接数
        :param total: 连接上限（<=0 时按 0 使用率处理，避免除零）
        """
        ratio = (used / total) if total > 0 else 0.0
        now = time.monotonic()
        with self._lock:
            samples = self._history.setdefault(name, deque(maxlen=256))
            samples.append((now, ratio))

    def evaluate(self) -> list[str]:
        """评估全部池，返回应触发双条件告警的池名列表。

        判定逻辑（规范 §18.5）：
        1) 第一条件：最新采样使用率 ≥ high_usage_ratio（当前处于高水位）；
        2) 第二条件：从最近一次低于阈值的时间点起算，持续时长 ≥ sustain_minutes；
           窗口内全部高于阈值时，保守从窗口最早样本起算（真实持续可能更长）。
        """
        now = time.monotonic()
        triggered: list[str] = []
        with self._lock:
            for name, samples in list(self._history.items()):
                # 仅保留时间窗口内样本（更早的旧样本不参与判定，防陈旧误报）
                recent = [s for s in samples if now - s[0] <= self._window_seconds]
                if not recent:
                    continue
                latest_ratio = recent[-1][1]
                if latest_ratio < self._config.high_usage_ratio:
                    continue  # 第一条件未满足：当前未达高水位，不告警
                below_times = [t for t, r in recent if r < self._config.high_usage_ratio]
                start = max(below_times) if below_times else recent[0][0]
                sustained = now - start
                if sustained >= self._config.sustain_minutes * 60.0:
                    triggered.append(name)
        return triggered

    def reset(self, name: str) -> None:
        """清除某池的历史采样（池关闭/重建时调用，防止旧样本导致误报）"""
        with self._lock:
            self._history.pop(name, None)
