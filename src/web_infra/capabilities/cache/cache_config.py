"""
缓存配置

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 缓存配置（规范 §8 / 附录 A.6，含 §8.3 热点 Key TTL 抖动配置）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CacheConfig(BaseModel):
    """缓存配置（规范 §8 / 附录 A.6）"""

    max_size: int = Field(default=10000, description="缓存容量上限（防止内存无界增长）")
    default_ttl: int = Field(default=300, description="默认过期时间（秒）")
    default_ttl_jitter_seconds: float = Field(
        default=5.0,
        description="默认 TTL 抖动上限（秒，规范 §8.3 防缓存雪崩；0 关闭抖动）",
    )
    remote_default_ttl: int = Field(
        default=300,
        description="分布式缓存参考 TTL（秒，规范 §8.3：本地缓存 TTL 以其为基准钳制，防止本地缓存拖长分布式 TTL 语义）",
    )
    local_ttl_ratio_limit: float = Field(
        default=1.0 / 3,
        description="本地缓存 TTL 不得超过分布式 TTL 的比例上限（默认 1/3，规范 §8.3：本地 TTL ≤ 分布式 TTL 的 1/3）",
    )
