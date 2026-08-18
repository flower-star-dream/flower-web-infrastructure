"""
并发控制模块

@Author: 花海
@Date: 2026/08/14 22:30
@Description: 导出单供应商并发控制能力（AI 规范 §5.2）：执行槽 + 有界排队 + 超时快速失败。
"""
from web_infra.capabilities.ai.concurrency.concurrency_guard import ConcurrencyGuard

__all__ = [
    "ConcurrencyGuard",
]
