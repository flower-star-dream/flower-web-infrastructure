"""
配额管理器

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 模型调用配额管理（AI 规范 §5.3/§6.2）：
              按租户/用户/场景维度设置调用次数、Token 与成本预算；
              超限返回 E1-RATE-000（调用/Token 超限，本地限流）或 E4-AI-005（成本配额耗尽）。
              AI-2 整改：check_and_consume 覆盖 chat/stream/embed 调用次数维度（入口统一检查），
              consume_usage 仅累计 Token/成本（不重复计调用次数），超限由后续入口检查拦截。
"""
from __future__ import annotations

import logging

from web_infra.ai.quota.quota_config import QuotaConfig
from web_infra.ai.quota.quota_store import QuotaStoreInterface
from web_infra.ai.quota.in_memory_quota_store import InMemoryQuotaStore
from web_infra.error import BizException, CommonErrorCode
from web_infra.error.ai_error_code import AiErrorCode

logger = logging.getLogger("web_infra.ai.quota")


class QuotaManager:
    """配额管理器：检查并消耗调用次数 / Token / 成本预算"""

    def __init__(self, store: QuotaStoreInterface | None = None, default_config: QuotaConfig | None = None) -> None:
        """初始化配额管理器。

        :param store: 配额计数存储（默认内存实现；多实例注入 Redis 实现）
        :param default_config: 默认配额配置（调用方未显式传 config 时使用）
        """
        self._store = store or InMemoryQuotaStore()
        self._default_config = default_config or QuotaConfig()

    async def check_and_consume(
        self,
        scope: str,
        scope_value: str,
        *,
        tokens: int = 0,
        cost: float = 0.0,
        config: QuotaConfig | None = None,
    ) -> None:
        """按窗口累计一次调用并校验配额，超限抛对应错误码。

        计数先累计再校验（窗口内边缘超额计入本次，防止绕过边界）。

        :param scope: 配额维度（tenant / user / scene，AI 规范 §5.3）
        :param scope_value: 维度值（如租户 ID / 用户 ID / 场景名）
        :param tokens: 本次 Token 用量
        :param cost: 本次成本（元）
        :param config: 本次配额配置（默认用构造时配置）
        :raises BizException: 调用次数/Token 超限抛 E1-RATE-000；成本超限抛 E4-AI-005
        """
        if not scope or not scope_value:
            raise ValueError("scope 与 scope_value 不能为空")
        cfg = config or self._default_config
        key = f"quota:{scope}:{scope_value}"
        counter = await self._store.incr(key, calls=1, tokens=tokens, cost=cost, window_seconds=cfg.window_seconds)

        if cfg.max_calls and counter.calls > cfg.max_calls:
            raise BizException(CommonErrorCode.RATE_LIMITED, message=f"调用次数配额超限（{scope}:{scope_value}）")
        if cfg.max_tokens and counter.tokens > cfg.max_tokens:
            raise BizException(CommonErrorCode.RATE_LIMITED, message=f"Token 配额超限（{scope}:{scope_value}）")
        if cfg.max_cost and counter.cost > cfg.max_cost:
            raise BizException(AiErrorCode.AI_QUOTA_EXHAUSTED, message=f"成本预算已耗尽（{scope}:{scope_value}）")

    async def consume_usage(
        self,
        scope: str,
        scope_value: str,
        *,
        tokens: int = 0,
        cost: float = 0.0,
        config: QuotaConfig | None = None,
    ) -> None:
        """仅累计 Token/成本配额（AI-2：Token/成本配额覆盖 chat/stream/embed），不增加调用次数。

        网关在模型调用成功后按实际用量调用本方法累计；本次调用已完成、用量不可回滚，
        因此累计后超限不抛错，仅记录告警，由下一次入口 check_and_consume 基于累计值
        （counter.tokens/counter.cost）统一拦截（遵循"计数先累计再校验"防绕过边界原则）。

        :param scope: 配额维度（tenant / user / scene，AI 规范 §5.3）
        :param scope_value: 维度值（如租户 ID / 用户 ID / 场景名）
        :param tokens: 本次实际 Token 用量
        :param cost: 本次实际成本（元）
        :param config: 本次配额配置（默认用构造时配置）
        """
        if not scope or not scope_value:
            raise ValueError("scope 与 scope_value 不能为空")
        cfg = config or self._default_config
        key = f"quota:{scope}:{scope_value}"
        counter = await self._store.incr(key, calls=0, tokens=tokens, cost=cost, window_seconds=cfg.window_seconds)
        if cfg.max_tokens and counter.tokens > cfg.max_tokens:
            logger.warning(
                "ai_quota_tokens_exceeded_after_usage scope=%s value=%s tokens=%s max_tokens=%s",
                scope, scope_value, counter.tokens, cfg.max_tokens,
            )
        if cfg.max_cost and counter.cost > cfg.max_cost:
            logger.warning(
                "ai_quota_cost_exceeded_after_usage scope=%s value=%s cost=%s max_cost=%s",
                scope, scope_value, counter.cost, cfg.max_cost,
            )
