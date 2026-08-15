"""
MinIO 对象存储配置

@Author: 花海
@Date: 2026/08/14 10:00
@Description: MinIO 对象存储配置（规范 §22）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class MinioStorageConfig(BaseModel):
    """MinIO 对象存储配置（规范 §22）"""

    endpoint: str = Field(default="localhost:9000", description="MinIO 服务地址")
    access_key: str = Field(default="", description="访问密钥（应走环境变量注入，规范 §15.2）")
    secret_key: str = Field(default="", description="访问密钥（应走环境变量注入，规范 §15.2）")
    secure: bool = Field(default=False, description="是否使用 HTTPS")
    default_bucket: str = Field(default="default", description="默认桶名")
    presign_expires: int = Field(default=600, description="签名 URL 有效期（秒，规范 §22.3 建议 ≤ 10min）")
