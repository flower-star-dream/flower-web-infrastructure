"""
模型网关配置

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 统一模型网关配置（AI 规范 §2.2/§2.3）：场景路由（主备模型）、默认场景与配额配置。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from web_infra.ai.quota.quota_config import QuotaConfig


@dataclass(frozen=True)
class RouteEntry:
    """场景路由条目：主模型 + 备用模型（主失败降级顺序，AI 规范 §2.3）"""

    primary: str  # 主模型逻辑名
    backups: tuple[str, ...] = ()  # 备用模型逻辑名（按降级顺序）


@dataclass(frozen=True)
class ModelGatewayConfig:
    """统一模型网关配置"""

    routes: dict[str, RouteEntry] = field(default_factory=dict)  # 场景 -> 路由条目
    default_scene: str = ""  # 默认场景（无匹配时回退，空则抛 E4-AI-001）
    quota: QuotaConfig | None = None  # 模型网关级配额（可选，按租户维度）
