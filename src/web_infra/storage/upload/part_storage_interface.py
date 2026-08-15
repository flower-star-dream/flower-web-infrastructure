"""
分片存储接口

@Author: 花海
@Date: 2026/08/14 19:30
@Description: 分片上传的底层分片存储抽象接口（规范 §22.4）：
              逐片存取、断点续传列出已传分片、合并与合并后清理。
              本地磁盘与 MinIO 分段上传为两种实现。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PartStorageInterface(Protocol):
    """分片存储抽象接口"""

    async def save_part(self, upload_id: str, part_number: int, data: bytes) -> None:
        """保存单个分片（重试幂等，覆盖同分片重传，规范 §22.4 断点续传）"""
        ...

    async def list_parts(self, upload_id: str) -> list[int]:
        """列出已存在分片序号（升序）"""
        ...

    async def read_part(self, upload_id: str, part_number: int) -> bytes:
        """读取单个分片内容（合并校验 MD5 时使用）"""
        ...

    async def merge(self, upload_id: str, object_key: str) -> int:
        """按分片序号合并为完整对象，返回合并后大小（字节）；合并后清理分片"""
        ...

    async def remove_task(self, upload_id: str) -> None:
        """清理任务全部分片与临时记录（合并后/取消时，§22.4）"""
        ...
