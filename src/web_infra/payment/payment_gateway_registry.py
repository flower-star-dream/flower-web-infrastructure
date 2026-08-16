"""
支付网关注册表

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 支付网关渠道注册表：按渠道名注册/查询 PaymentGateway 实现。
              未注册渠道时 get 抛 E4-PAY-001（支付渠道未配置/未注册）。
"""
from __future__ import annotations

from web_infra.payment.payment_error_code import PaymentErrorCode
from web_infra.payment.payment_gateway_interface import PaymentGateway


class PaymentGatewayRegistry:
    """支付网关渠道注册表（类级注册，全局装配）"""

    _gateways: dict[str, PaymentGateway] = {}

    @classmethod
    def register(cls, name: str, gateway: PaymentGateway) -> None:
        """注册渠道（同名覆盖）"""
        cls._gateways[name] = gateway

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销渠道（不存在时静默）"""
        cls._gateways.pop(name, None)

    @classmethod
    def get(cls, name: str) -> PaymentGateway:
        """按渠道名查询；未注册抛 E4-PAY-001"""
        gateway = cls._gateways.get(name)
        if gateway is None:
            raise PaymentErrorCode.PAY_NOT_CONFIGURED.to_exception(message=f"支付渠道未注册：{name}")
        return gateway

    @classmethod
    def registered_names(cls) -> list[str]:
        """已注册渠道名清单"""
        return list(cls._gateways)
