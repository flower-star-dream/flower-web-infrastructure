"""
支付网关统一抽象接口

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 支付网关 SPI（渠道统一抽象）：下单/查单/关单/退款/查退款。
              业务代码只依赖本接口，金额统一 Decimal（元），渠道差异内部屏蔽。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from web_infra.payment.payment_order import PaymentOrder
from web_infra.payment.prepay_request import PaymentPrepayRequest
from web_infra.payment.prepay_response import PaymentPrepayResponse
from web_infra.payment.refund_request import PaymentRefundRequest
from web_infra.payment.refund_response import PaymentRefundResponse


@runtime_checkable
class PaymentGateway(Protocol):
    """支付网关统一抽象（下单/查单/关单/退款/查退款）"""

    async def prepay(self, request: PaymentPrepayRequest) -> PaymentPrepayResponse:
        """下单：按场景返回 prepay_id/调起参数/code_url/h5_url"""
        ...

    async def query_order(self, out_trade_no: str) -> PaymentOrder | None:
        """按商户订单号查单；不存在返回 None"""
        ...

    async def close_order(self, out_trade_no: str) -> None:
        """关闭订单（订单支付失败重新下单前调用，防重复支付）"""
        ...

    async def refund(self, request: PaymentRefundRequest) -> PaymentRefundResponse:
        """申请退款（out_refund_no 幂等）"""
        ...

    async def query_refund(self, out_refund_no: str) -> PaymentRefundResponse | None:
        """按商户退款单号查退款；不存在返回 None"""
        ...
