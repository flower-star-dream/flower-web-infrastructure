"""
统一模型网关模块

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 导出统一模型网关（AI 规范 §2.2/§2.3）：场景路由（主备降级）与模型网关收敛组件。
              全称"模型网关"，避免与聚合各类服务的 API 网关命名冲突。
"""
from web_infra.ai.model_gateway.model_gateway_config import RouteEntry, ModelGatewayConfig
from web_infra.ai.model_gateway.model_router import ModelRouter
from web_infra.ai.model_gateway.model_gateway import ModelGateway

__all__ = [
    "RouteEntry",
    "ModelGatewayConfig",
    "ModelRouter",
    "ModelGateway",
]
