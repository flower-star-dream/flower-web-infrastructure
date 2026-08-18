"""
对象存储配置

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 对象存储配置（规范 §22）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class StorageConfig(BaseModel):
    """对象存储配置（规范 §22）"""

    base_dir: str = Field(default="./data", description="本地存储根目录（本地实现用）")
    presign_expires: int = Field(default=600, description="签名 URL 有效期（秒，规范 §22.3 建议 ≤ 10min）")
    max_upload_size: int = Field(default=5 * 1024 * 1024, description="上传大小上限（字节，规范 §22.2）")
