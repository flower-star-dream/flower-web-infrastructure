"""
AI 配额管理模块

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 导出模型调用配额管理（AI 规范 §5.3/§6.2）：配额配置、计数存储 SPI（内存默认）与配额管理器。
"""
from web_infra.ai.quota.quota_config import QuotaConfig
from web_infra.ai.quota.quota_store import QuotaCounter, QuotaStoreInterface
from web_infra.ai.quota.in_memory_quota_store import InMemoryQuotaStore
from web_infra.ai.quota.quota_manager import QuotaManager

__all__ = [
    "QuotaConfig",
    "QuotaCounter",
    "QuotaStoreInterface",
    "InMemoryQuotaStore",
    "QuotaManager",
]
