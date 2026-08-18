"""
支付风控守卫（PaymentRiskGuard）

@Author: 花海
@Date: 2026/08/17
@Description: 风控与限额校验（规范 §9）：下单前逐项校验——单笔限额 / 日累计 / 月累计
              （超限 E4-PAY-005）、下单频次（超限 E4-PAY-006）、可疑拆分（大额拆分
              多笔接近单笔限额，命中 E4-PAY-007 风控拦截）。
              限额累计 Decimal 精确 + 原子（§9.4 红线）；拦截必须留痕（审计由业务接入，
              §9.3：风控命中落审计可申诉）。注入渠道骨架 prepay 前置校验（可选，None 跳过）。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from web_infra.capabilities.payment.payment_error_code import PaymentErrorCode
from web_infra.capabilities.payment.risk.limit_counter_store import LimitCounterStoreInterface
from web_infra.capabilities.payment.risk.payment_limit_config import LimitRule

# 计数 key 前缀（§9.1 累计维度：用户 + 渠道；日/月按自然窗口）
DAILY_KEY_TEMPLATE = "pay:limit:daily:{user_id}:{channel}:{date}"
MONTHLY_KEY_TEMPLATE = "pay:limit:monthly:{user_id}:{channel}:{month}"
FREQUENCY_KEY_TEMPLATE = "pay:freq:{user_id}:{channel}"
SPLIT_KEY_TEMPLATE = "pay:split:{user_id}:{channel}"


class PaymentRiskGuard:
    """支付风控守卫：下单前限额/频次/可疑交易校验（§9）"""

    def __init__(self, counter_store: LimitCounterStoreInterface) -> None:
        """初始化风控守卫。

        :param counter_store: 限额/频次计数存储（Redis 跨实例；InMemory 单实例测试）
        """
        self._counter_store = counter_store

    async def check_prepay(self, user_id: int, channel: str, amount: Decimal, rule: LimitRule) -> None:
        """下单前风控校验（§9.1/§9.2/§9.3），任一命中抛对应错误码。

        :param user_id: 用户 ID
        :param channel: 渠道名
        :param amount: 本次支付金额（元）
        :param rule: 渠道限额规则（未配置字段不限制）
        :raises WebInfraException: E4-PAY-005 限额超限 / E4-PAY-006 频次超限 / E4-PAY-007 风控拦截
        """
        # §9.1 单笔限额
        if rule.per_transaction is not None and amount > rule.per_transaction:
            raise PaymentErrorCode.PAY_LIMIT_EXCEEDED.to_exception(
                message=f"单笔限额 {rule.per_transaction} 元，本次 {amount} 元超限（§9.1）"
            )
        # §9.1 日累计限额（Decimal 精确 + 原子累加，§9.4）
        if rule.daily_limit is not None:
            today = date.today().isoformat()
            daily = await self._counter_store.add_and_get(
                DAILY_KEY_TEMPLATE.format(user_id=user_id, channel=channel, date=today), amount,
            )
            if daily > rule.daily_limit:
                raise PaymentErrorCode.PAY_LIMIT_EXCEEDED.to_exception(
                    message=f"日累计限额 {rule.daily_limit} 元，当前累计 {daily} 元超限（§9.1）"
                )
        # §9.1 月累计限额
        if rule.monthly_limit is not None:
            month = date.today().strftime("%Y-%m")
            monthly = await self._counter_store.add_and_get(
                MONTHLY_KEY_TEMPLATE.format(user_id=user_id, channel=channel, month=month), amount,
            )
            if monthly > rule.monthly_limit:
                raise PaymentErrorCode.PAY_LIMIT_EXCEEDED.to_exception(
                    message=f"月累计限额 {rule.monthly_limit} 元，当前累计 {monthly} 元超限（§9.1）"
                )
        # §9.2 下单频次（同用户 + 渠道窗口计数）
        if rule.frequency_window_seconds > 0 and rule.max_attempts > 0:
            attempts = await self._counter_store.add_and_get(
                FREQUENCY_KEY_TEMPLATE.format(user_id=user_id, channel=channel),
                Decimal("1"), rule.frequency_window_seconds,
            )
            if attempts > rule.max_attempts:
                raise PaymentErrorCode.PAY_FREQUENCY_LIMITED.to_exception(
                    message=f"下单过于频繁，窗口内最多 {rule.max_attempts} 次（§9.2）"
                )
        # §9.3 可疑拆分：窗口内接近单笔限额的大额笔数（大额拆分绕过限额，命中风控拦截）
        if rule.per_transaction is not None and rule.suspicious_split_count > 0:
            threshold = rule.per_transaction * rule.suspicious_split_ratio
            if amount >= threshold:
                split_count = await self._counter_store.add_and_get(
                    SPLIT_KEY_TEMPLATE.format(user_id=user_id, channel=channel),
                    Decimal("1"), rule.frequency_window_seconds or 3600,
                )
                if split_count >= rule.suspicious_split_count:
                    raise PaymentErrorCode.PAY_RISK_BLOCKED.to_exception(
                        message=f"检测到大额拆分交易（{int(split_count)} 笔接近单笔限额），风控拦截（§9.3）"
                    )
