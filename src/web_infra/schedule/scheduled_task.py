"""
定时任务定义

@Author: 花海
@Date: 2026/08/14 18:00
@Description: 定时任务模型（规范 §23.1：任务必须含全局唯一标识、模块归属、执行间隔与描述，禁止匿名任务）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable


@dataclass(frozen=True)
class ScheduledTask:
    """定时任务定义（规范 §23.1 / §23.3）"""

    name: str  # 全局唯一标识（如 order:job:message-outbox-publish，命名含模块归属）
    module: str  # 模块归属
    interval_seconds: float  # 执行间隔（秒）
    handler: Callable[[], Awaitable[None]]  # 异步执行函数
    description: str = ""  # 任务描述（禁止匿名任务）
    timeout_seconds: float | None = None  # 执行超时（规范 §23.3：超时中断并告警）
    consecutive_failure_limit: int = 3  # 连续失败阈值：达到后自动暂停并告警（规范 §23.4）
