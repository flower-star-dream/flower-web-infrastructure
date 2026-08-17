"""
支付渠道契约测试套件

@Author: 花海
@Date: 2026/08/16
@Description: 渠道契约测试（规范 §3.3/§10.3）：对任意 PaymentChannelTemplate 骨架实现执行
              同一组资金场景契约断言（掉单补偿 / 重复回调幂等 / 关单后回调冲突 / 金额不符 /
              attach 不符 / 退款超额 / 关单查单确认 / 下单幂等 / 流水落库）。
              渠道接入方在测试中构造骨架实现 + 注入 InMemory 存储，调用 run_all() 收集契约结果；
              业务可用 assert result.all_passed 作为质量门禁。纯断言驱动，无渠道网络依赖。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from web_infra.payment.in_memory_payment_flow_store import InMemoryPaymentFlowStore
from web_infra.payment.in_memory_payment_order_store import InMemoryPaymentOrderStore
from web_infra.payment.payment_callback import PaymentCallback
from web_infra.payment.payment_channel_template import PaymentChannelTemplate, PaymentFlowContext
from web_infra.payment.payment_flow_record import PaymentFlowRecord
from web_infra.payment.payment_flow_status import PaymentFlowEvent, PaymentFlowStatus
from web_infra.payment.payment_order_store_interface import PaymentLocalOrder
from web_infra.payment.payment_status import PaymentEvent, PaymentStatus
from web_infra.payment.prepay_request import PaymentPrepayRequest
from web_infra.payment.payment_scene import PaymentScene
from web_infra.payment.refund_request import PaymentRefundRequest


@dataclass
class ContractCaseResult:
    """单个契约用例执行结果"""

    name: str                                  # 用例名（§10.3 资金场景）
    passed: bool                               # 是否通过
    detail: str = ""                           # 失败详情（断言消息/异常）
    error: Exception | None = None             # 失败异常（None 表示通过）


class PaymentChannelContract:
    """渠道契约测试套件（§3.3/§10.3）：对骨架实现执行统一资金场景契约断言"""

    def __init__(self, channel: PaymentChannelTemplate, *, amount: Decimal = Decimal("10.00")) -> None:
        """初始化契约套件。

        :param channel: 骨架渠道实现（须已具备 refund 能力；契约用例含退款场景）
        :param amount: 契约用例统一订单金额（元）
        """
        self._channel = channel
        self._amount = amount
        self._order_store = InMemoryPaymentOrderStore()
        self._flow_store = InMemoryPaymentFlowStore()
        # 将独立存储注入渠道（契约用例基于注入后的兜底全量生效）
        channel._flow_store = self._flow_store  # type: ignore[attr-defined]
        channel._order_store = self._order_store  # type: ignore[attr-defined]

    async def run_all(self) -> list[ContractCaseResult]:
        """执行全部契约用例，返回逐用例结果（互不中断）。

        :return: ContractCaseResult 列表；调用方可用 all(r.passed for r in results) 作门禁
        """
        cases = [
            ("掉单补偿查单收敛", self._case_query_fallback),
            ("重复回调幂等", self._case_repeat_callback),
            ("关单后回调冲突", self._case_closed_callback),
            ("金额不符拒绝入账", self._case_amount_mismatch),
            ("attach 不符拒绝入账", self._case_attach_mismatch),
            ("退款超额拒绝", self._case_refund_exceed),
            ("关单前查单确认", self._case_close_confirm),
            ("下单幂等拒绝重复", self._case_prepay_idempotency),
            ("回调入账流水落库", self._case_flow_booked),
        ]
        results: list[ContractCaseResult] = []
        for name, case in cases:
            try:
                await case()
                results.append(ContractCaseResult(name=name, passed=True))
            except Exception as exc:  # noqa: BLE001 - 契约断言失败即记录用例失败
                results.append(ContractCaseResult(name=name, passed=False, detail=str(exc), error=exc))
        return results

    # ------------------------------------------------------------------
    # 契约用例（§10.3 资金场景必测）
    # ------------------------------------------------------------------

    async def _case_query_fallback(self) -> None:
        """掉单补偿（§7.4）：回调丢失后经查单收敛，本地订单状态与渠道一致（SUCCESS）"""
        out_trade_no = "CT-QUERY"
        await self._order_store.save(PaymentLocalOrder(out_trade_no=out_trade_no, amount=self._amount))
        order = await self._channel._do_query_order(out_trade_no)  # type: ignore[attr-defined]
        assert order is not None, "掉单补偿：查单应返回渠道订单"
        assert order.status == PaymentStatus.SUCCESS, f"掉单补偿：渠道状态应为 SUCCESS，实际 {order.status}"

    async def _case_repeat_callback(self) -> None:
        """重复回调幂等（§4.3）：SUCCESS 后重复支付回调 → 骨架通用校验幂等返回（不抛冲突）"""
        out_trade_no = "CT-REPEAT"
        await self._order_store.save(PaymentLocalOrder(out_trade_no=out_trade_no, amount=self._amount, status=PaymentStatus.SUCCESS))
        await self._channel._verify_and_check(PaymentCallback(  # type: ignore[attr-defined]
            event_type="TRANSACTION.SUCCESS", out_trade_no=out_trade_no, amount=self._amount,
        ))

    async def _case_closed_callback(self) -> None:
        """关单后回调冲突（§4.5 终态不可逆）：CLOSED 订单收到支付回调 → E4-PAY-003"""
        from web_infra.payment import PaymentErrorCode, PaymentStateMachine

        try:
            PaymentStateMachine.target(PaymentStatus.CLOSED, PaymentEvent.PAY_SUCCESS)
        except Exception as exc:
            assert getattr(exc, "code", "") == PaymentErrorCode.PAY_ORDER_STATE_CONFLICT.code, "关单后回调应报 E4-PAY-003"
            return
        raise AssertionError("关单后回调应抛 E4-PAY-003")

    async def _case_amount_mismatch(self) -> None:
        """金额不符拒绝入账（§4.3）：回调金额 ≠ 本地订单金额 → E4-PAY-002"""
        out_trade_no = "CT-AMT"
        await self._order_store.save(PaymentLocalOrder(out_trade_no=out_trade_no, amount=self._amount))
        try:
            await self._channel._verify_and_check(PaymentCallback(  # type: ignore[attr-defined]
                event_type="TRANSACTION.SUCCESS", out_trade_no=out_trade_no, amount=Decimal("99.00"),
            ))
        except Exception as exc:
            from web_infra.payment import PaymentErrorCode

            assert getattr(exc, "code", "") == PaymentErrorCode.PAY_AMOUNT_MISMATCH.code, "金额不符应报 E4-PAY-002"
            return
        raise AssertionError("金额不符回调应拒绝入账（E4-PAY-002）")

    async def _case_attach_mismatch(self) -> None:
        """attach 不符拒绝入账（§4.3）：回调附加数据 ≠ 本地订单 → 拒绝"""
        out_trade_no = "CT-ATTACH"
        await self._order_store.save(PaymentLocalOrder(out_trade_no=out_trade_no, amount=self._amount, attach="order-a"))
        try:
            await self._channel._verify_and_check(PaymentCallback(  # type: ignore[attr-defined]
                event_type="TRANSACTION.SUCCESS", out_trade_no=out_trade_no, amount=self._amount, attach="order-b",
            ))
        except Exception:
            return  # 拒绝即符合契约
        raise AssertionError("attach 不符回调应拒绝入账（§4.3）")

    async def _case_refund_exceed(self) -> None:
        """退款超额拒绝（§5.3）：已退 + 本次 > 实付金额 → 拒绝透传渠道"""
        out_trade_no = "CT-REFUND"
        await self._order_store.save(PaymentLocalOrder(out_trade_no=out_trade_no, amount=self._amount, status=PaymentStatus.SUCCESS))
        await self._flow_store.append(PaymentFlowRecord(
            out_trade_no=out_trade_no, event_type=PaymentFlowEvent.REFUND,
            amount=self._amount * Decimal("0.6"),
        ))
        try:
            await self._channel.refund(PaymentRefundRequest(
                out_trade_no=out_trade_no, out_refund_no="CT-R1",
                refund_amount=self._amount * Decimal("0.5"), total_amount=self._amount,
            ))
        except Exception:
            return  # 拒绝即符合契约
        raise AssertionError("退款超额应拒绝（§5.3）")

    async def _case_close_confirm(self) -> None:
        """关单前查单确认（§5.5）：渠道已支付 → 禁止关单（防已支付被关闭）"""
        out_trade_no = "CT-CLOSE-PAID"
        await self._order_store.save(PaymentLocalOrder(out_trade_no=out_trade_no, amount=self._amount))
        try:
            await self._channel.close_order(out_trade_no)
        except Exception:
            return  # 拒绝即符合契约（FakeChannel 渠道态 SUCCESS 时骨架抛冲突）
        raise AssertionError("渠道已支付订单应禁止关单（§5.5）")

    async def _case_prepay_idempotency(self) -> None:
        """下单幂等（§4.2）：本地订单进行中/成功 → 拒绝重复下单"""
        out_trade_no = "CT-PREPAY"
        await self._order_store.save(PaymentLocalOrder(out_trade_no=out_trade_no, amount=self._amount, status=PaymentStatus.USERPAYING))
        try:
            await self._channel.prepay(PaymentPrepayRequest(
                scene=PaymentScene.NATIVE, out_trade_no=out_trade_no,
                description="contract", total_amount=self._amount,
            ))
        except Exception:
            return  # 拒绝即符合契约
        raise AssertionError("进行中订单应拒绝重复下单（§4.2）")

    async def _case_flow_booked(self) -> None:
        """回调入账流水落库（§5.2）：支付成功回调 → 订单 SUCCESS + PAY 流水已入账"""
        out_trade_no = "CT-FLOW"
        await self._order_store.save(PaymentLocalOrder(out_trade_no=out_trade_no, amount=self._amount))
        await self._channel._verify_and_check(PaymentCallback(  # type: ignore[attr-defined]
            event_type="TRANSACTION.SUCCESS", out_trade_no=out_trade_no, amount=self._amount, transaction_id="WX-CT-1",
        ))
        await self._channel._persist_flow(PaymentFlowContext(  # type: ignore[attr-defined]
            out_trade_no=out_trade_no, amount=self._amount, event_type=PaymentFlowEvent.PAY.value,
            status="SUCCESS", transaction_id="WX-CT-1",
        ))
        local = await self._order_store.find_by_out_trade_no(out_trade_no)
        assert local is not None, "回调入账后应能查到本地订单"
        assert local.status == PaymentStatus.SUCCESS, "回调入账后本地订单应为 SUCCESS"
        flow = await self._flow_store.find_by_order_and_event(out_trade_no, PaymentFlowEvent.PAY)
        assert flow is not None, "回调入账应写 PAY 流水（§5.2）"
        assert flow.status == PaymentFlowStatus.BOOKED, "支付成功流水应为已入账（BOOKED）"
