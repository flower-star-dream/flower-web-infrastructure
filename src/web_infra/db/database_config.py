"""
数据库连接配置

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 数据库连接配置（连接池参数对齐规范 §14.1 / 附录 A.7）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    """数据库连接配置（连接池参数对齐规范 §14.1 / 附录 A.7）"""

    url: str = Field(default="", description="数据库连接地址")
    max_pool_size: int = Field(default=20, description="最大连接数")
    min_idle: int = Field(default=10, description="最小空闲连接数")
    connect_timeout: int = Field(default=3, description="获取连接超时（秒）")
    socket_timeout: int = Field(default=30, description="读写超时（秒）")
    leak_detection_threshold: int = Field(default=10, description="连接泄漏检测阈值（秒）")
