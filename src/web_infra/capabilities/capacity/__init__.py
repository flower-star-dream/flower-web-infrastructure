"""
并发访问能力评估模块（Capacity Assessment）

@Author: 花海
@Date: 2026/08/18 09:00
@Description: 容量评估模块（设计文档《并发访问能力评估设计.md》）：静态估算 + 运行时推断
              双轨评估系统并发访问能力，四类输出（/capacity HTTP 端点 + HTML / CLI /
              Prometheus Gauge）。按 yml 开关装配（app.capacity.enabled），不加入
              capability 注册表（非前置依赖链能力）；需显式 `from web_infra.capabilities.capacity
              import ...` 引入（不随 web_infra 顶层全量导出，与 payment 可选能力一致）。
"""
from web_infra.capabilities.capacity.assessor import CapacityAssessor
from web_infra.capabilities.capacity.capacity_config import CapacityConfig, DiagnosticAccessConfig, RemoteProbeConfig
from web_infra.capabilities.capacity.capacity_endpoint import register_capacity_endpoints, render_capacity_html
from web_infra.capabilities.capacity.report import (
    CapacityReport,
    ClusterSnapshot,
    ComponentCapacity,
    InstanceSnapshot,
    RuntimeSnapshot,
    StaticEstimation,
)

__all__ = [
    "CapacityAssessor",
    "CapacityConfig",
    "CapacityReport",
    "ClusterSnapshot",
    "ComponentCapacity",
    "DiagnosticAccessConfig",
    "InstanceSnapshot",
    "RemoteProbeConfig",
    "RuntimeSnapshot",
    "StaticEstimation",
    "register_capacity_endpoints",
    "render_capacity_html",
]
