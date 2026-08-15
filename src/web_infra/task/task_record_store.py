"""
任务记录存储接口

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 异步任务记录存储抽象（SPI，规范 §23.4），
              默认内存实现，多实例/需持久化时可对接 MySQL 等实现。
              更新采用乐观锁（version 匹配），避免并发覆盖终态。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from web_infra.task.task_record import TaskRecord


class TaskRecordStoreInterface(ABC):
    """任务记录存储接口"""

    @abstractmethod
    async def save(self, record: TaskRecord) -> None:
        """保存任务记录（新增或全量覆盖）"""
        raise NotImplementedError

    @abstractmethod
    async def load(self, task_id: str) -> TaskRecord | None:
        """按任务 ID 加载记录；未找到返回 None"""
        raise NotImplementedError

    @abstractmethod
    async def update(self, record: TaskRecord) -> bool:
        """乐观锁更新：仅当存储中版本与 record.version 一致时写入并自增版本。

        :return: 更新是否成功（版本不一致返回 False，调用方应视为终态已保护）
        """
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[TaskRecord]:
        """列出全部任务记录（供死任务扫描等场景遍历）"""
        raise NotImplementedError
