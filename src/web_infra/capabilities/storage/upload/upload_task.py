"""
分片上传任务

@Author: 花海
@Date: 2026/08/14 19:30
@Description: 分片上传任务记录（规范 §22.4：上传任务初始化 -> 分片记录 -> 合并后清理临时任务记录）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from web_infra.capabilities.storage.upload.upload_status import UploadStatus


@dataclass
class UploadTask:
    """分片上传任务记录"""

    upload_id: str  # 上传任务唯一标识（断点续传定位依据，§22.4）
    file_name: str  # 原始文件名
    file_size: int  # 文件总大小（字节）
    chunk_size: int  # 分片大小（字节）
    total_chunks: int  # 总分片数
    uploaded_parts: set[int] = field(default_factory=set)  # 已上传分片序号（断点续传依据）
    status: UploadStatus = UploadStatus.INITIALIZED  # 任务状态
    object_key: str = ""  # 合并完成后的对象 Key
    created_at: datetime | None = None  # 任务创建时间（临时任务记录清理依据，§22.4）
