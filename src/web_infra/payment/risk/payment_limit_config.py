"""
支付限额配置（PaymentLimitConfig）

@Author: 花海
@Date: 2026/08/17
@Description: 限额/频次规则配置（规范 §9.1/§9.2）：工程可配置约束——单笔限额、日/月累计限额、
              下单频次限制按渠道/场景配置，配置中心管理即时生效（§9.1 限额配置化）。
              限额累计用 Decimal 精确计算 + 原子更新（§9.1/§9.4 红线：禁止浮点/非原子）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class LimitRule:
    """单渠道/场景限额规则（未配置字段不限制）"""

    per_transaction: Decimal | None = None  # 单笔限额（元，§9.1）
    daily_limit: Decimal | None = None  # 日累计限额（元，按用户，§9.1）
    monthly_limit: Decimal | None = None  # 月累计限额（元，按用户，§9.1）
    frequency_window_seconds: int = 0  # 下单频次窗口（秒，0 = 不限频次，§9.2）
    max_attempts: int = 0  # 窗口内最大下单次数（0 = 不限，§9.2）
    suspicious_split_count: int = 3  # 可疑拆分判定：窗口内接近单笔限额的笔数阈值（§9.3）
    suspicious_split_ratio: Decimal = Decimal("0.9")  # 接近单笔限额的比例阈值（≥ 90% 单笔限额）


class PaymentLimitConfig:
    """限额规则配置容器（渠道名 → LimitRule，配置中心注入）"""

    def __init__(self, rules: dict[str, LimitRule] | None = None) -> None:
        """初始化配置容器。

        :param rules: 渠道名 → 限额规则；缺省空（不限制，需配置后生效）
        """
        self._rules: dict[str, LimitRule] = dict(rules or {})

    def rule_for(self, channel: str) -> LimitRule:
        """按渠道取限额规则（未配置返回空规则 = 不限制）"""
        return self._rules.get(channel, LimitRule())

    def upsert(self, channel: str, rule: LimitRule) -> None:
        """更新渠道限额规则（配置中心推送即时生效，§9.1）"""
        self._rules[channel] = rule
