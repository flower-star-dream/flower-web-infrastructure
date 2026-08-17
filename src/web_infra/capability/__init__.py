"""
能力模块

@Author: 花海
@Date: 2026/08/17 16:00
@Description: 能力契约与依赖包含规则：框架声明能力契约（SPI）与前置包含关系（用户系统 → 鉴权 → 支付，
              以此类推），具体业务实现交由业务层（如脚手架 user-service）。启用能力时按包含关系
              自动启用前置（enable / resolve / validate，见 CapabilityRegistry）。
"""
from web_infra.capability.capability import Capability
from web_infra.capability.capability_error import CapabilityError
from web_infra.capability.capability_registry import CapabilityRegistry
from web_infra.capability.capability_resolution import CapabilityResolution
from web_infra.capability.capability_validation import CapabilityValidation
from web_infra.capability.builtin_capabilities import register_builtin_capabilities

# 导入即注册框架内置能力（幂等），业务可继续 register 自定义能力
register_builtin_capabilities()

__all__ = [
    "Capability",
    "CapabilityError",
    "CapabilityRegistry",
    "CapabilityResolution",
    "CapabilityValidation",
]
