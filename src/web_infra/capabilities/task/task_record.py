"""
任务记录模型

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 异步任务执行记录（规范 §23.4：任务 ID/状态/提交时间/心跳/耗时/结果/失败原因）。
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from web_infra.capabilities.task.task_status import TaskStatus


def _new_task_id() -> str:
    """生成任务唯一标识"""
    return uuid.uuid4().hex


class TaskRecord(BaseModel):
    """异步任务执行记录"""

    task_id: str = Field(default_factory=_new_task_id, description="任务唯一标识")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="任务状态")
    submit_at: float = Field(default_factory=time.time, description="提交时间（unix 秒）")
    start_at: float | None = Field(default=None, description="开始执行时间")
    end_at: float | None = Field(default=None, description="结束时间")
    heartbeat_at: float | None = Field(default=None, description="最近心跳时间")
    version: int = Field(default=0, description="乐观锁版本号（并发更新校验）")
    error: str = Field(default="", description="失败原因")
    payload: dict[str, Any] = Field(default_factory=dict, description="任务元信息（如业务参数）")

    @property
    def duration_seconds(self) -> float | None:
        """任务执行耗时（秒）；未结束返回 None"""
        if self.start_at is None or self.end_at is None:
            return None
        return round(self.end_at - self.start_at, 3)
