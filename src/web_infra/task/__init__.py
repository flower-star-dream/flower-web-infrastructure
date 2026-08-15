"""
异步任务调度模块

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 导出异步任务调度框架：任务状态、任务记录、存储 SPI（内存默认）与任务执行器
              （规范 §9 异步化 / §23 任务执行记录）。
"""
from web_infra.task.task_status import TaskStatus
from web_infra.task.task_record import TaskRecord
from web_infra.task.task_record_store import TaskRecordStoreInterface
from web_infra.task.in_memory_task_record_store import InMemoryTaskRecordStore
from web_infra.task.task_executor import TaskExecutor

__all__ = [
    "TaskStatus",
    "TaskRecord",
    "TaskRecordStoreInterface",
    "InMemoryTaskRecordStore",
    "TaskExecutor",
]
