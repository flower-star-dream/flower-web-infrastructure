"""
Token 计费与成本统计

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 模型调用 Token 用量打点与成本统计（AI 规范 §5.2/§14）：
              按输入/输出 Token 单价计算单次成本，结构化日志输出，
              可选 UsageRecordStore 持久化；内存聚合按模型/租户/场景分组。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from typing import Any

from web_infra.capabilities.ai.model_config import ModelConfig
from web_infra.capabilities.ai.usage import Usage
from web_infra.capabilities.ai.usage_record import UsageRecord
from web_infra.capabilities.ai.usage_record_store import UsageRecordStoreInterface

logger = logging.getLogger("web_infra.capabilities.ai.usage_accounting")


class UsageAccounting:
    """Token 计费与成本统计"""

    def __init__(self, record_store: UsageRecordStoreInterface | None = None) -> None:
        """初始化计费组件。

        :param record_store: 用量记录持久化（默认 None：仅日志输出）
        """
        self._record_store = record_store
        self._aggregates: dict[tuple[str, ...], dict[str, float]] = defaultdict(
            lambda: {"prompt_tokens": 0.0, "completion_tokens": 0.0, "total_tokens": 0.0, "cost": 0.0, "calls": 0.0}
        )
        # 线程安全：record（写）与 aggregate（读）可能被不同线程/事件循环并发调用
        self._lock = threading.Lock()

    def record(
        self,
        usage: Usage,
        model_code: str,
        *,
        provider: str = "",
        tenant_id: str = "",
        scene: str = "",
        input_price_per_1k: float | None = None,
        output_price_per_1k: float | None = None,
    ) -> UsageRecord:
        """记录一次调用用量并计算成本。

        :param usage: Token 用量
        :param model_code: 模型编码
        :param provider: 供应商
        :param tenant_id: 租户标识
        :param scene: 调用场景
        :param input_price_per_1k: 输入单价（元/1K），默认 0
        :param output_price_per_1k: 输出单价（元/1K），默认 0
        :return: 用量记录（含成本）
        """
        prompt_tokens = usage.prompt_tokens or 0
        completion_tokens = usage.completion_tokens or 0
        total_tokens = usage.total_tokens or (prompt_tokens + completion_tokens)
        input_price = input_price_per_1k if input_price_per_1k is not None else 0.0
        output_price = output_price_per_1k if output_price_per_1k is not None else 0.0
        cost = round(prompt_tokens / 1000 * input_price + completion_tokens / 1000 * output_price, 6)

        record = UsageRecord(
            model_code=model_code,
            provider=provider,
            tenant_id=tenant_id,
            scene=scene,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost=cost,
        )

        # 结构化日志打点（默认出口）
        logger.info(
            "ai_usage model=%s tenant=%s scene=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s cost=%s",
            model_code, tenant_id, scene, prompt_tokens, completion_tokens, total_tokens, cost,
        )
        # 内存聚合（供统计查询；线程安全互斥）
        with self._lock:
            for keys in self._aggregate_keys(record):
                agg = self._aggregates[keys]
                agg["prompt_tokens"] += prompt_tokens
                agg["completion_tokens"] += completion_tokens
                agg["total_tokens"] += total_tokens
                agg["cost"] += cost
                agg["calls"] += 1

        # 持久化（配置 store 时异步写入；无事件循环时降级为日志提示）
        if self._record_store is not None:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                logger.warning("ai_usage_store_skipped_no_loop model=%s", model_code)
            else:
                asyncio.create_task(self._record_store.save(record))
        return record

    def record_from_config(self, usage: Usage, config: ModelConfig, *, tenant_id: str = "", scene: str = "") -> UsageRecord:
        """按模型配置（含单价）记录用量，成本依据配置单价计算"""
        return self.record(
            usage,
            config.model_code,
            provider=config.provider,
            tenant_id=tenant_id,
            scene=scene,
            input_price_per_1k=config.input_price_per_1k,
            output_price_per_1k=config.output_price_per_1k,
        )

    def aggregate(self, group_by: tuple[str, ...] = ("model_code",)) -> list[dict[str, Any]]:
        """按单一维度聚合用量（模型/租户/场景）。

        :param group_by: 分组维度（单元素元组），取值 model_code/provider/tenant_id/scene
        :return: 聚合结果列表（含维度字段 + 各项累计）
        """
        with self._lock:
            results: list[dict[str, Any]] = []
            for (name, value), agg in self._aggregates.items():
                if name not in group_by:
                    continue
                item: dict[str, Any] = {name: value}
                item.update({k: round(v, 4) for k, v in agg.items()})
                results.append(item)
        return results

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _aggregate_keys(self, record: UsageRecord) -> list[tuple[str, str]]:
        """生成当前记录参与的各维度聚合 Key（维度名, 维度值）"""
        return [
            ("model_code", record.model_code),
            ("tenant_id", record.tenant_id),
            ("scene", record.scene),
        ]
