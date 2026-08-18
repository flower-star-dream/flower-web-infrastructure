"""
RocketMQ 配置

@Author: 花海
@Date: 2026/08/14 10:00
@Description: RocketMQ 配置（规范 §9 / 附录 A.13）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RocketMqConfig(BaseModel):
    """RocketMQ 配置（规范 §9 / 附录 A.13）"""

    name_server: str = Field(default="localhost:9876", description="NameServer 地址")
    group_name: str = Field(default="web-producer-group", description="生产者组名")
    send_timeout: int = Field(default=3000, description="发送超时（毫秒）")
