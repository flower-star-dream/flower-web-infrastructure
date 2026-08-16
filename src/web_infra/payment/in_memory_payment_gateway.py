"""
内存支付网关（测试/单机默认实现）

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 内存支付网关实现（PaymentGateway SPI 默认实现）：内存字典模拟订单/退款状态流转，
              供单机/测试场景使用；多实例需替换为真实渠道实现（如 WeChatPayProvider）。
"""
from __future__ import annotations

from decimal import Decimal

from web_infra.payment.payment_gateway_interface import PaymentGateway
from web_infra.payment.payment_order import PaymentOrder
from web_infra.payment.payment_scene import PaymentScene
from web_infra.payment.payment_status import PaymentStatus, RefundStatus
from web_infra.payment.prepay_request import PaymentPrepayRequest
from web_infra.payment.prepay_response import PaymentPrepayResponse
from web_infra.payment.refund_request import PaymentRefundRequest
from web_infra.payment.refund_response import PaymentRefundResponse


class InMemoryPaymentGateway(PaymentGateway):
    """内存支付网关（PaymentGateway SPI 默认实现，单机/测试）"""

    def __init__(self) -> None:
        self._orders: dict[str, PaymentOrder] = {}
        self._refunds: dict[str, PaymentRefundResponse] = {}

    def seed_order(self, order: PaymentOrder) -> None:
        """测试辅助：直接注入订单（模拟已支付等状态）"""
        self._orders[order.out_trade_no] = order

    async def prepay(self, request: PaymentPrepayRequest) -> PaymentPrepayResponse:
        prepay_id = f"prepay-{request.out_trade_no}"
        self._orders[request.out_trade_no] = PaymentOrder(
            out_trade_no=request.out_trade_no,
            status=PaymentStatus.NOTPAY,
            total_amount=request.total_amount,
            payer_total=Decimal("0.00"),
        )
        if request.scene == PaymentScene.NATIVE:
            return PaymentPrepayResponse(scene=request.scene, code_url=f"weixin://pay/{prepay_id}")
        if request.scene == PaymentScene.H5:
            return PaymentPrepayResponse(scene=request.scene, h5_url=f"https://example.com/pay/{prepay_id}")
        return PaymentPrepayResponse(scene=request.scene, prepay_id=prepay_id, pay_params={"prepay_id": prepay_id})

    async def query_order(self, out_trade_no: str) -> PaymentOrder | None:
        return self._orders.get(out_trade_no)

    async def close_order(self, out_trade_no: str) -> None:
        order = self._orders.get(out_trade_no)
        if order is not None:
            self._orders[out_trade_no] = order.model_copy(update={"status": PaymentStatus.CLOSED})

    async def refund(self, request: PaymentRefundRequest) -> PaymentRefundResponse:
        response = PaymentRefundResponse(
            out_refund_no=request.out_refund_no,
            status=RefundStatus.SUCCESS,
            refund_amount=request.refund_amount,
        )
        self._refunds[request.out_refund_no] = response
        return response

    async def query_refund(self, out_refund_no: str) -> PaymentRefundResponse | None:
        return self._refunds.get(out_refund_no)
