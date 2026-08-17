"""
内存支付网关（测试/单机默认实现）

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 内存支付网关实现（PaymentGateway SPI 默认实现）：继承 PaymentChannelTemplate 渠道骨架
              （规范 §3.1），固化下单幂等/退款能力位/关单查单确认/回调校验等资金流程，渠道特有
              逻辑（_do_*）用内存字典模拟订单/退款状态流转。注入 flow_store/order_store 后骨架兜底
              全量生效（流水落库/本地幂等）；未注入时降级为纯渠道调用（兼容 SPI 直用）。
              多实例需替换为真实渠道实现（如 WeChatPayProvider）。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from web_infra.payment.payment_callback import PaymentCallback
from web_infra.payment.payment_channel_template import PaymentChannelTemplate
from web_infra.payment.payment_gateway_interface import PaymentGateway
from web_infra.payment.payment_order import PaymentOrder
from web_infra.payment.payment_scene import PaymentScene
from web_infra.payment.payment_status import PaymentStatus, RefundStatus
from web_infra.payment.prepay_request import PaymentPrepayRequest
from web_infra.payment.prepay_response import PaymentPrepayResponse
from web_infra.payment.refund_request import PaymentRefundRequest
from web_infra.payment.refund_response import PaymentRefundResponse


class InMemoryPaymentGateway(PaymentChannelTemplate, PaymentGateway):
    """内存支付网关（PaymentGateway SPI 默认实现，单机/测试；骨架兜底：下单幂等/退款能力位/关单查单确认/流水落库）"""

    # 能力位声明（规范 §3.4）：内存渠道支持查单/关单/退款/查退款/回调解析（回调经业务入口 validate_callback）
    capabilities = frozenset({"query_order", "close_order", "refund", "query_refund", "parse_callback"})

    def __init__(self, flow_store: Any | None = None, order_store: Any | None = None) -> None:
        """初始化内存渠道（骨架注入可选存储）。

        :param flow_store: 支付流水存储（PaymentFlowStoreInterface，§5.2）；None 时跳过流水落库（降级）
        :param order_store: 本地支付订单存储（PaymentOrderStoreInterface，§4.2/§5.5）；None 时跳过本地幂等/校验（降级）
        """
        super().__init__(flow_store=flow_store, order_store=order_store)
        self._orders: dict[str, PaymentOrder] = {}
        self._refunds: dict[str, PaymentRefundResponse] = {}

    def seed_order(self, order: PaymentOrder) -> None:
        """测试辅助：直接注入订单（模拟已支付等状态）"""
        self._orders[order.out_trade_no] = order

    # ------------------------------------------------------------------
    # PaymentGateway 协议：骨架 final 之外的查询入口
    # ------------------------------------------------------------------

    async def query_order(self, out_trade_no: str) -> PaymentOrder | None:
        """按商户订单号查单（渠道权威状态，掉单补偿/关单确认依赖，§3.2/§3.4）"""
        return await self._do_query_order(out_trade_no)

    async def query_refund(self, out_refund_no: str) -> PaymentRefundResponse | None:
        """按商户退款单号查退款（退款超时兜底，§7.6）"""
        return await self._do_query_refund(out_refund_no)

    # ------------------------------------------------------------------
    # 渠道特有逻辑（骨架 final 流程不可覆写）
    # ------------------------------------------------------------------

    async def _do_prepay(self, request: PaymentPrepayRequest) -> PaymentPrepayResponse:
        """渠道特有下单：内存记录订单（NOTPAY）并返回场景对应调起参数"""
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

    async def _do_query_order(self, out_trade_no: str) -> PaymentOrder | None:
        """渠道特有查单：内存订单记录（无记录返回 None）"""
        return self._orders.get(out_trade_no)

    async def _do_close_order(self, out_trade_no: str) -> None:
        """渠道特有关单（骨架 close_order 已前置查单确认未支付，§5.5）"""
        order = self._orders.get(out_trade_no)
        if order is not None:
            self._orders[out_trade_no] = order.model_copy(update={"status": PaymentStatus.CLOSED})

    async def _parse_callback(self, headers: Mapping[str, str], body: str) -> PaymentCallback | None:
        """渠道特有回调验签：内存渠道无渠道签名体系，不支持回调报文解析（业务走 validate_callback 入口）"""
        raise NotImplementedError("InMemoryPaymentGateway 不支持回调报文验签解析；业务回调入口请使用 validate_callback")

    async def _do_refund(self, request: PaymentRefundRequest) -> PaymentRefundResponse:
        """渠道特有退款：内存记录退款单并返回 SUCCESS"""
        response = PaymentRefundResponse(
            out_refund_no=request.out_refund_no,
            status=RefundStatus.SUCCESS,
            refund_amount=request.refund_amount,
        )
        self._refunds[request.out_refund_no] = response
        return response

    async def _do_query_refund(self, out_refund_no: str) -> PaymentRefundResponse | None:
        """渠道特有查退款：内存退款单记录（无记录返回 None）"""
        return self._refunds.get(out_refund_no)
