"""
微信支付渠道实现

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 微信支付渠道实现（PaymentGateway SPI）：JSAPI/Native/H5/App 四场景下单、
              查单、关单、退款、查退款。金额统一 Decimal 元，内部转分。
              接口路径参考官方文档（pay.weixin.qq.com/doc/v3/merchant）。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from web_infra.payment.payment_constant import PaymentConstant
from web_infra.payment.payment_error_code import PaymentErrorCode
from web_infra.payment.payment_gateway_interface import PaymentGateway
from web_infra.payment.payment_order import PaymentOrder
from web_infra.payment.payment_scene import PaymentScene
from web_infra.payment.payment_status import PaymentStatus, RefundStatus
from web_infra.payment.prepay_request import PaymentPrepayRequest
from web_infra.payment.prepay_response import PaymentPrepayResponse
from web_infra.payment.refund_request import PaymentRefundRequest
from web_infra.payment.refund_response import PaymentRefundResponse
from web_infra.payment.provider.wechat.wechat_pay_client import WeChatPayClient
from web_infra.payment.payment_config import WechatPayConfig
from web_infra.payment.provider.wechat.wechat_signer import WeChatSigner

# 场景 -> 下单接口路径
SCENE_PATH: dict[PaymentScene, str] = {
    PaymentScene.JSAPI: "/v3/pay/transactions/jsapi",
    PaymentScene.NATIVE: "/v3/pay/transactions/native",
    PaymentScene.H5: "/v3/pay/transactions/h5",
    PaymentScene.APP: "/v3/pay/transactions/app",
}


class WeChatPayProvider(PaymentGateway):
    """微信支付渠道实现（PaymentGateway SPI，四场景）"""

    def __init__(self, config: WechatPayConfig, client: WeChatPayClient | None = None) -> None:
        self._config = config
        self._client = client or WeChatPayClient(config)

    async def prepay(self, request: PaymentPrepayRequest) -> PaymentPrepayResponse:
        """下单：按场景组装请求体并返回 prepay_id/调起参数/code_url/h5_url"""
        path = SCENE_PATH.get(request.scene)
        if path is None:
            raise PaymentErrorCode.PAY_SCENE_UNSUPPORTED.to_exception(message=f"不支持的支付场景：{request.scene}")
        if request.scene == PaymentScene.JSAPI and not request.openid:
            raise PaymentErrorCode.PAY_SCENE_UNSUPPORTED.to_exception(message="JSAPI 场景缺少 openid")
        if request.scene == PaymentScene.H5 and not request.client_ip:
            raise PaymentErrorCode.PAY_SCENE_UNSUPPORTED.to_exception(message="H5 场景缺少 client_ip")

        payload: dict = {
            "appid": self._config.appid,
            "mchid": self._config.mchid,
            "description": request.description,
            "out_trade_no": request.out_trade_no,
            "notify_url": request.notify_url or self._config.notify_url,
            "amount": {
                "total": self._to_fen(request.total_amount),
                "currency": PaymentConstant.BIZ_PAY_CURRENCY_CNY,
            },
        }
        if request.time_expire is not None:
            payload["time_expire"] = self._format_expire(request.time_expire)
        if request.attach is not None:
            payload["attach"] = request.attach
        if request.scene == PaymentScene.JSAPI:
            payload["payer"] = {"openid": request.openid}
        elif request.scene == PaymentScene.H5:
            payload["scene_info"] = {"payer_client_ip": request.client_ip, "h5_info": {"type": "Wap"}}

        data = await self._client.request("POST", path, payload)
        prepay_id = data.get("prepay_id")
        if request.scene == PaymentScene.NATIVE:
            return PaymentPrepayResponse(scene=request.scene, code_url=data.get("code_url"))
        if request.scene == PaymentScene.H5:
            return PaymentPrepayResponse(scene=request.scene, h5_url=data.get("h5_url"))
        if request.scene == PaymentScene.APP:
            return PaymentPrepayResponse(scene=request.scene, prepay_id=prepay_id, pay_params=self._app_pay_params(prepay_id))
        return PaymentPrepayResponse(scene=request.scene, prepay_id=prepay_id, pay_params=self._jsapi_pay_params(prepay_id))

    async def query_order(self, out_trade_no: str) -> PaymentOrder | None:
        """查单：微信 404 转 None（对齐 FeignClient 404→None 语义）"""
        path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}?mchid={self._config.mchid}"
        data = await self._client.request("GET", path, not_found_ok=True)
        if data is None:
            return None
        amount = data.get("amount") or {}
        return PaymentOrder(
            out_trade_no=data["out_trade_no"],
            transaction_id=data.get("transaction_id"),
            status=PaymentStatus(data.get("trade_state", "NOTPAY")),
            total_amount=self._to_yuan(amount.get("total", 0)),
            payer_total=self._to_yuan(amount.get("payer_total", amount.get("total", 0))),
            paid_at=self._parse_time(data.get("success_time")),
        )

    async def close_order(self, out_trade_no: str) -> None:
        """关闭订单（订单支付失败重新下单前调用，防重复支付）"""
        path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}/close"
        await self._client.request("POST", path, {"mchid": self._config.mchid})

    async def refund(self, request: PaymentRefundRequest) -> PaymentRefundResponse:
        """申请退款（out_refund_no 幂等）"""
        payload: dict = {
            "out_trade_no": request.out_trade_no,
            "out_refund_no": request.out_refund_no,
            "amount": {
                "refund": self._to_fen(request.refund_amount),
                "total": self._to_fen(request.total_amount),
                "currency": PaymentConstant.BIZ_PAY_CURRENCY_CNY,
            },
        }
        if request.refund_notify_url:
            payload["notify_url"] = request.refund_notify_url
        if request.reason:
            payload["reason"] = request.reason
        data = await self._client.request("POST", "/v3/refund/domestic/refunds", payload)
        amount = data.get("amount") or {}
        return PaymentRefundResponse(
            out_refund_no=data["out_refund_no"],
            refund_id=data.get("refund_id"),
            status=RefundStatus(data.get("status", "PROCESSING")),
            refund_amount=self._to_yuan(amount.get("refund", request.refund_amount)),
        )

    async def query_refund(self, out_refund_no: str) -> PaymentRefundResponse | None:
        """按商户退款单号查退款；不存在返回 None"""
        path = f"/v3/refund/domestic/refunds/{out_refund_no}?mchid={self._config.mchid}"
        data = await self._client.request("GET", path, not_found_ok=True)
        if data is None:
            return None
        amount = data.get("amount") or {}
        return PaymentRefundResponse(
            out_refund_no=data["out_refund_no"],
            refund_id=data.get("refund_id"),
            status=RefundStatus(data.get("status", "PROCESSING")),
            refund_amount=self._to_yuan(amount.get("refund", 0)),
        )

    # ------------------------------------------------------------------
    # 私有工具
    # ------------------------------------------------------------------

    def _jsapi_pay_params(self, prepay_id: str) -> dict:
        """JSAPI/小程序调起支付参数（二次签名，签名串 appId\\nts\\nnonce\\npackage\\nRSA）"""
        appid = self._config.appid
        timestamp = WeChatSigner.new_timestamp()
        nonce = WeChatSigner.new_nonce()
        package = f"prepay_id={prepay_id}"
        message = "\n".join([appid, timestamp, nonce, package, "RSA"])
        return {
            "appId": appid,
            "timeStamp": timestamp,
            "nonceStr": nonce,
            "package": package,
            "signType": "RSA",
            "paySign": WeChatSigner.sign(self._private_key_pem(), message),
        }

    def _app_pay_params(self, prepay_id: str) -> dict:
        """App 调起支付参数（签名串 appId\\nts\\nnonce\\nprepay_id=xxx）"""
        appid = self._config.appid
        timestamp = WeChatSigner.new_timestamp()
        nonce = WeChatSigner.new_nonce()
        message = "\n".join([appid, timestamp, nonce, f"prepay_id={prepay_id}"])
        return {
            "appid": appid,
            "partnerid": self._config.mchid,
            "prepayid": prepay_id,
            "package": "Sign=WXPay",
            "noncestr": nonce,
            "timestamp": timestamp,
            "sign": WeChatSigner.sign(self._private_key_pem(), message),
        }

    def _private_key_pem(self) -> str:
        """商户 API 私钥（内容优先，其次文件路径）"""
        if self._config.private_key:
            return self._config.private_key
        with open(self._config.private_key_path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _to_fen(amount: Decimal) -> int:
        """元 → 分"""
        return int(amount * Decimal(PaymentConstant.BIZ_PAY_AMOUNT_SCALE))

    @staticmethod
    def _to_yuan(fen: int) -> Decimal:
        """分 → 元"""
        return Decimal(fen) / Decimal(PaymentConstant.BIZ_PAY_AMOUNT_SCALE)

    @staticmethod
    def _format_expire(dt: datetime) -> str:
        """datetime → 微信 ISO8601（含 +08:00 格式时区）"""
        base = dt.strftime("%Y-%m-%dT%H:%M:%S")
        offset = dt.strftime("%z")
        return f"{base}{offset[:3]}:{offset[3:]}" if offset else base

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        """微信 ISO8601 → datetime（解析失败返回 None）"""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
