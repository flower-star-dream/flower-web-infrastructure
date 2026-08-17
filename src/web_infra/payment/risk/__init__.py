"""
风控限额模块（risk）

@Author: 花海
@Date: 2026/08/17
@Description: 风控与限额（规范 §9）：限额规则配置（§9.1 配置化）、限额/频次计数存储
              （§9.1/§9.2 Decimal 精确 + 原子）、风控守卫（单笔/日/月限额 E4-PAY-005、
              频次 E4-PAY-006、可疑拆分 E4-PAY-007）。
"""
from web_infra.payment.risk.limit_counter_store import InMemoryLimitCounterStore, LimitCounterStoreInterface
from web_infra.payment.risk.payment_limit_config import LimitRule, PaymentLimitConfig
from web_infra.payment.risk.payment_risk_guard import (
    DAILY_KEY_TEMPLATE,
    FREQUENCY_KEY_TEMPLATE,
    MONTHLY_KEY_TEMPLATE,
    SPLIT_KEY_TEMPLATE,
    PaymentRiskGuard,
)

__all__ = [
    "LimitRule",
    "PaymentLimitConfig",
    "LimitCounterStoreInterface",
    "InMemoryLimitCounterStore",
    "PaymentRiskGuard",
    "DAILY_KEY_TEMPLATE",
    "MONTHLY_KEY_TEMPLATE",
    "FREQUENCY_KEY_TEMPLATE",
    "SPLIT_KEY_TEMPLATE",
]
