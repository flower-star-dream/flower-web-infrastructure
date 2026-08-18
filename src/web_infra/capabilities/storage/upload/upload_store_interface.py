"""
分片上传任务存储接口

@Author: 花海
@Date: 2026/08/14 19:30
@Description: 分片上传任务记录存储抽象接口（规范 §22.4：初始化上传任务 -> 分片记录 -> 合并后清理临时任务记录）。
              内存实现默认，多实例可扩展 Redis/MySQL。
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from web_infra.capabilities.storage.upload.upload_task import UploadTask


@runtime_checkable
class UploadStoreInterface(Protocol):
    """分片上传任务存储抽象接口"""

    async def create(self, task: UploadTask) -> UploadTask:
        """创建上传任务（初始化，规范 §22.4）"""
        ...

    async def get(self, upload_id: str) -> UploadTask | None:
        """按 upload_id 查询任务（断点续传定位依据）"""
        ...

    async def mark_part_uploaded(self, upload_id: str, part_number: int) -> None:
        """记录分片上传成功（断点续传查询已传分片）"""
        ...

    async def list_uploaded_parts(self, upload_id: str) -> list[int]:
        """列出已上传分片序号（客户端断点续传）"""
        ...

    async def complete(self, upload_id: str, object_key: str) -> None:
        """标记任务合并完成（合并后清理临时任务记录，§22.4）"""
        ...

    async def remove(self, upload_id: str) -> None:
        """定向删除指定上传任务记录（取消上传/合并完成时仅清理当前任务，§22.4，禁止误删其他任务）"""
        ...

    async def cleanup(self, before: datetime) -> int:
        """清理过期未完成/已完成任务记录（配合定时任务，§22.4 临时目录 TTL 清理）"""
        ...
