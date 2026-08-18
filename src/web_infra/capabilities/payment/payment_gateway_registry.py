"""
支付网关注册表

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 支付网关渠道注册表：按渠道名注册/查询 PaymentGateway 实现。
              未注册渠道时 get 抛 E4-PAY-001（支付渠道未配置/未注册）。
              能力位启动校验（规范 §3.4）：渠道声明 capabilities 时，缺必选能力
              （query_order/close_order/parse_callback）拒绝注册；声明 refund 未配套
              query_refund 告警降级；未声明 capabilities 的渠道记录告警后放行（兼容过渡）。
"""
from __future__ import annotations

import logging
from threading import Lock
from typing import Any

from web_infra.capabilities.payment.payment_error_code import PaymentErrorCode
from web_infra.capabilities.payment.payment_gateway_interface import PaymentGateway

logger = logging.getLogger("web_infra.capabilities.payment.registry")

# 必选能力（规范 §3.4）：掉单补偿/关单确认/回调解析兜底依赖
REQUIRED_CAPABILITIES = frozenset({"query_order", "close_order", "parse_callback"})
# 可选能力：退款必须配套查退款（退款超时无法查单兜底，§7.6）
OPTIONAL_CAPABILITIES = frozenset({"refund", "query_refund", "bill_parse"})


class PaymentGatewayRegistry:
    """支付网关渠道注册表（类级注册，全局装配；类级锁保护并发 register/get，与 FeignClient 工厂一致）"""

    _gateways: dict[str, PaymentGateway] = {}
    _lock = Lock()

    @classmethod
    def register(cls, name: str, gateway: PaymentGateway) -> None:
        """注册渠道（同名覆盖）；能力位启动校验（规范 §3.4）：
        声明 capabilities 的渠道缺必选能力 → 拒绝注册；未声明 → 告警放行（兼容过渡）。

        :param name: 渠道名
        :param gateway: 渠道实现
        :raises ValueError: 渠道缺必选能力（query_order/close_order/parse_callback）
        """
        cls._validate_capabilities(name, gateway)
        with cls._lock:
            cls._gateways[name] = gateway

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销渠道（不存在时静默）"""
        with cls._lock:
            cls._gateways.pop(name, None)

    @classmethod
    def get(cls, name: str) -> PaymentGateway:
        """按渠道名查询；未注册抛 E4-PAY-001（锁内 check-then-act，防并发注册竞态）"""
        with cls._lock:
            gateway = cls._gateways.get(name)
        if gateway is None:
            raise PaymentErrorCode.PAY_NOT_CONFIGURED.to_exception(message=f"支付渠道未注册：{name}")
        return gateway

    @classmethod
    def registered_names(cls) -> list[str]:
        """已注册渠道名清单"""
        with cls._lock:
            return list(cls._gateways)

    # ------------------------------------------------------------------
    # 内部：能力位启动校验（§3.4）
    # ------------------------------------------------------------------

    @classmethod
    def _validate_capabilities(cls, name: str, gateway: Any) -> None:
        """能力位校验：缺必选能力拒绝注册；可选能力配套告警降级（§3.4 红线）"""
        capabilities = getattr(gateway, "capabilities", None)
        if not capabilities:
            logger.warning(
                "支付渠道 %s 未声明 capabilities（规范 §3.4），跳过能力校验（建议渠道声明 query_order/close_order/parse_callback）",
                name,
            )
            return
        missing = REQUIRED_CAPABILITIES - set(capabilities)
        if missing:
            raise ValueError(f"支付渠道 {name} 缺必选能力 {sorted(missing)}，拒绝注册（规范 §3.4）")
        if "refund" in capabilities and "query_refund" not in capabilities:
            logger.warning(
                "支付渠道 %s 声明 refund 但未声明 query_refund，退款超时无法查单兜底，降级人工（§7.6）", name
            )
        if "bill_parse" not in capabilities:
            logger.warning("支付渠道 %s 未声明 bill_parse，对账走查单兜底（降级）", name)
