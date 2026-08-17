"""
支付渠道契约测试套件测试

@Author: 花海
@Date: 2026/08/16
@Description: 验证契约测试套件（PaymentChannelContract，§3.3/§10.3）对假渠道执行全部资金场景
              契约用例均通过；回调模拟器（PaymentCallbackSimulator，§10.3）报文构造正确。
"""
from decimal import Decimal
from typing import Any, Mapping

import pytest

from web_infra.payment import (
    PaymentCallback,
    PaymentChannelTemplate,
    PaymentOrder,
    PaymentPrepayRequest,
    PaymentPrepayResponse,
    PaymentScene,
    PaymentStatus,
)
from web_infra.payment.testing import PaymentCallbackSimulator, PaymentChannelContract


class _ContractChannel(PaymentChannelTemplate):
    """契约测试假渠道：渠道态恒 SUCCESS（掉单补偿/关单确认场景）"""

    capabilities = frozenset({"query_order", "close_order", "parse_callback", "refund", "query_refund"})

    def __init__(self, **kwargs: Any) -> None:
        super().__init__()
        self.close_called = False

    async def _do_prepay(self, request: PaymentPrepayRequest) -> PaymentPrepayResponse:
        return PaymentPrepayResponse(scene=request.scene, prepay_id="prepay-1")

    async def _do_query_order(self, out_trade_no: str) -> Any:
        return PaymentOrder(
            out_trade_no=out_trade_no, status=PaymentStatus.SUCCESS,
            total_amount=Decimal("10.00"), payer_total=Decimal("10.00"),
        )

    async def _do_close_order(self, out_trade_no: str) -> None:
        self.close_called = True

    async def _parse_callback(self, headers: Mapping[str, str], body: str) -> PaymentCallback | None:
        return PaymentCallback(event_type="TRANSACTION.SUCCESS", out_trade_no="x", amount=Decimal("0.01"))

    async def _do_refund(self, request: Any) -> Any:
        from web_infra.payment import PaymentRefundResponse

        return PaymentRefundResponse(out_refund_no=request.out_refund_no, refund_id="REF-1", refund_amount=request.refund_amount)


@pytest.mark.asyncio
async def test_contract_suite_all_passed():
    """契约套件：全部资金场景用例通过（§3.3 质量门禁）"""
    contract = PaymentChannelContract(_ContractChannel())
    results = await contract.run_all()
    failed = [r for r in results if not r.passed]
    assert not failed, f"契约用例失败：{[(r.name, r.detail) for r in failed]}"
    assert len(results) == 9  # 9 个契约场景


def test_callback_simulator_build_success():
    """回调模拟器：支付成功报文字段完整（§10.3）"""
    sim = PaymentCallbackSimulator()
    headers, body = sim.build_success("T1", Decimal("10.00"), attach="order-1", transaction_id="WX-1")
    assert "Wechatpay-Timestamp" in headers
    callback = sim.to_callback(headers, body)
    assert callback.event_type == "TRANSACTION.SUCCESS"
    assert callback.out_trade_no == "T1"
    assert callback.amount == Decimal("10.00")
    assert callback.attach == "order-1"
    assert callback.transaction_id == "WX-1"


def test_callback_simulator_build_refund():
    """回调模拟器：退款成功报文含商户退款单号（§10.3）"""
    sim = PaymentCallbackSimulator()
    _, body = sim.build_refund_success("T1", "R1", Decimal("3.00"))
    callback = sim.to_callback({}, body)
    assert callback.event_type == "REFUND.SUCCESS"
    assert callback.mch_refund_no == "R1"
    assert callback.amount == Decimal("3.00")


def test_callback_simulator_amount_mismatch_payload():
    """回调模拟器：金额不符报文（§10.3/§4.3 场景注入）"""
    sim = PaymentCallbackSimulator()
    _, body = sim.build_amount_mismatch("T1", Decimal("10.00"), Decimal("99.00"))
    callback = sim.to_callback({}, body)
    assert callback.amount == Decimal("99.00")  # 回调金额 ≠ 本地金额（本地 10.00）


def test_callback_simulator_attach_mismatch_payload():
    """回调模拟器：attach 不符报文（§10.3/§4.3 场景注入）"""
    sim = PaymentCallbackSimulator()
    _, body = sim.build_attach_mismatch("T1", Decimal("10.00"), "order-a", "order-b")
    callback = sim.to_callback({}, body)
    assert callback.attach == "order-b"  # 回调 attach ≠ 本地 attach（order-a）


def test_callback_simulator_signer_hook():
    """回调模拟器：注入 signer 可补齐签名（§10.3 验签链路模拟）"""
    def fake_signer(headers: dict, body: str) -> dict:
        headers["Wechatpay-Signature"] = "sig"
        return headers

    headers, _ = PaymentCallbackSimulator(signer=fake_signer).build_success("T1", Decimal("1.00"))
    assert headers["Wechatpay-Signature"] == "sig"
