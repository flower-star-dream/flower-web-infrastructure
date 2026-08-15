"""
定时任务调度模块

@Author: 花海
@Date: 2026/08/14 18:00
@Description: 导出定时任务与调度器（规范 §23）：任务定义（唯一标识/模块/间隔/超时）与
              asyncio 调度器（可选分布式锁防多实例重复执行、连续失败自动暂停）。
"""
from web_infra.schedule.scheduled_task import ScheduledTask
from web_infra.schedule.task_scheduler import TaskScheduler

__all__ = [
    "ScheduledTask",
    "TaskScheduler",
]
