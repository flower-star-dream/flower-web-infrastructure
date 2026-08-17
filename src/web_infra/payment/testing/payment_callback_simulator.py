"""
支付回调模拟器

@Author: 花海
@Date: 2026/08/16
@Description: 回调模拟器（规范 §10.3 测试质量门禁）：构造渠道回调报文 (headers, body)，
              供单测/联调模拟渠道回调事件（支付成功 / 退款成功 / 金额不符 / attach 不符等）。
              不依赖具体渠道验签实现——签名由注入的 signer 回调完成（缺省空签名），
              测试渠道 _parse_callback 直接消费。设计为无状态工具类，线程安全。
"""
from __future__ import annotations

import json
import time
import uuid
from decimal import Decimal
from typing import Callable

from web_infra.payment.payment_callback import PaymentCallback

# signer 签名回调：入参 (headers, body)，返回补齐签名后的 headers
Signer = Callable[[dict, str], dict]


class PaymentCallbackSimulator:
    """支付回调模拟器（测试/联调组件，§10.3）"""

    def __init__(self, signer: Signer | None = None) -> None:
        """初始化模拟器。

        :param signer: 可选签名回调（对 headers/body 补签，模拟渠道真实验签链路）；缺省空签名
        """
        self._signer = signer

    def build_success(self, out_trade_no: str, amount: Decimal, *, attach: str | None = None,
                      transaction_id: str | None = None, timestamp: int | None = None) -> tuple[dict, str]:
        """构造支付成功回调报文（TRANSACTION.SUCCESS）。

        :param out_trade_no: 商户订单号
        :param amount: 支付金额（元）
        :param attach: 商户附加数据（与下单一致）
        :param transaction_id: 渠道交易号
        :param timestamp: 回调时间戳（缺省当前时间；可注入过期时间戳测重放拦截）
        :return: (headers, body) 回调报文
        """
        payload = {
            "event_type": "TRANSACTION.SUCCESS",
            "out_trade_no": out_trade_no,
            "amount": str(amount),
            "attach": attach,
            "transaction_id": transaction_id or f"WX-{uuid.uuid4().hex[:16]}",
            "raw": {"mchid": "1900000001"},
        }
        return self._pack(payload, timestamp)

    def build_refund_success(self, out_trade_no: str, out_refund_no: str, refund_amount: Decimal, *,
                             timestamp: int | None = None) -> tuple[dict, str]:
        """构造退款成功回调报文（REFUND.SUCCESS）。

        :param out_trade_no: 商户订单号
        :param out_refund_no: 商户退款单号
        :param refund_amount: 退款金额（元）
        :param timestamp: 回调时间戳（缺省当前时间）
        :return: (headers, body) 回调报文
        """
        payload = {
            "event_type": "REFUND.SUCCESS",
            "out_trade_no": out_trade_no,
            "amount": str(refund_amount),
            "mch_refund_no": out_refund_no,
            "raw": {"refund_status": "SUCCESS"},
        }
        return self._pack(payload, timestamp)

    def build_amount_mismatch(self, out_trade_no: str, local_amount: Decimal, callback_amount: Decimal, *,
                              timestamp: int | None = None) -> tuple[dict, str]:
        """构造金额不符回调（§4.3 测试：回调金额 ≠ 本地订单金额 → E4-PAY-002 场景）"""
        return self._pack({
            "event_type": "TRANSACTION.SUCCESS",
            "out_trade_no": out_trade_no,
            "amount": str(callback_amount),
            "raw": {"local_amount": str(local_amount)},
        }, timestamp)

    def build_attach_mismatch(self, out_trade_no: str, amount: Decimal, local_attach: str,
                              callback_attach: str, *, timestamp: int | None = None) -> tuple[dict, str]:
        """构造 attach 不符回调（§4.3 测试：回调附加数据 ≠ 本地订单 → 拒绝入账场景）"""
        return self._pack({
            "event_type": "TRANSACTION.SUCCESS",
            "out_trade_no": out_trade_no,
            "amount": str(amount),
            "attach": callback_attach,
            "raw": {"local_attach": local_attach},
        }, timestamp)

    def to_callback(self, headers: dict, body: str) -> PaymentCallback:
        """解析模拟报文为统一回调结构（等价于渠道层验签解密后的产物，供契约断言复用）"""
        payload = json.loads(body)
        return PaymentCallback(
            event_type=payload["event_type"],
            out_trade_no=payload["out_trade_no"],
            amount=Decimal(payload["amount"]),
            transaction_id=payload.get("transaction_id"),
            attach=payload.get("attach"),
            mch_refund_no=payload.get("mch_refund_no"),
            raw=payload.get("raw") or {},
        )

    # ------------------------------------------------------------------
    # 内部：打包报文 + 可选签名
    # ------------------------------------------------------------------

    def _pack(self, payload: dict, timestamp: int | None) -> tuple[dict, str]:
        """JSON 序列化 body + 构造 headers（时间戳/随机串，可选签名补齐）"""
        body = json.dumps(payload, ensure_ascii=False)
        headers = {
            "Content-Type": "application/json",
            "Wechatpay-Timestamp": str(timestamp if timestamp is not None else int(time.time())),
            "Wechatpay-Nonce": uuid.uuid4().hex,
            "Wechatpay-Signature": "",
        }
        if self._signer is not None:
            headers = self._signer(headers, body)
        return headers, body
