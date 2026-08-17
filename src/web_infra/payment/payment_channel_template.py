"""
支付渠道骨架类（模板方法层）

@Author: 花海
@Date: 2026/08/16
@Description: 渠道骨架类（Template Method，规范 §3.1）：固化四条资金/状态路径骨架
              （下单 prepay / 退款 refund / 关单 close_order / 回调入账 handle_callback），
              骨架 final 不可覆写，渠道实现方只填充 _do_*（必选抽象 / 可选默认不支持）与 _parse_callback。
              兜底由骨架统一编排：幂等检查（§4）→ 渠道调用 → 三态收敛 → 流水落库（§5.2）；
              关单前查单确认防已支付被关闭（§5.5）；回调经渠道层验签解密 + 通用层校验
              （时间戳/幂等/金额/attach/状态机，§2.3/§4.3）。
              依赖注入：flow_store（支付流水本地事务表，§5.2）与 order_store（本地支付订单，§4.2/§5.5）
              由业务实现；未注入时降级为纯渠道调用（兼容渠道 SPI 直用场景），注入后兜底全量生效。
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, final

from web_infra.error.common_error_code import CommonErrorCode
from web_infra.error.web_infra_exception import WebInfraException
from web_infra.monitoring.payment_metrics import record_callback, record_prepay, record_refund
from web_infra.payment.payment_callback import PaymentCallback
from web_infra.payment.payment_error_code import PaymentErrorCode
from web_infra.payment.payment_flow_record import PaymentFlowRecord
from web_infra.payment.payment_flow_status import PaymentFlowEvent, PaymentFlowStatus
from web_infra.payment.payment_order_store_interface import PaymentLocalOrder, PaymentOrderStoreInterface
from web_infra.payment.payment_state_machine import PaymentStateMachine
from web_infra.payment.payment_status import PaymentEvent, PaymentStatus
from web_infra.payment.prepay_request import PaymentPrepayRequest
from web_infra.payment.prepay_response import PaymentPrepayResponse
from web_infra.payment.refund_request import PaymentRefundRequest
from web_infra.payment.refund_response import PaymentRefundResponse

logger = logging.getLogger("web_infra.payment.channel")

# 渠道调用结果三态（规范 §7.4：失败/成功/未知严格区分，未知态只允许查证与对账兜底）
SUCCESS, FAILED, UNKNOWN = "SUCCESS", "FAILED", "UNKNOWN"


@dataclass
class PaymentFlowContext:
    """统一流水落库上下文（三态收敛输入，规范 §3.1）"""

    out_trade_no: str
    amount: Decimal | None = None
    event_type: str = ""
    status: str = SUCCESS  # 三态：SUCCESS / FAILED / UNKNOWN
    channel: str = ""
    transaction_id: str = ""
    out_refund_no: str = ""
    raw: dict | None = None
    is_reversal: bool = False
    original_flow_id: str = ""
    status_override: PaymentFlowStatus | None = None  # 账务状态覆盖（如待入账/已关闭）


class PaymentChannelTemplate(ABC):
    """渠道骨架类：prepay/refund/close_order/handle_callback 为 final 入口，_do_* / _parse_callback 由渠道实现方填充"""

    # 渠道能力位声明（规范 §3.4）：必选 query_order/close_order/parse_callback，可选 refund/query_refund
    capabilities: frozenset[str] = frozenset()

    def __init__(self, flow_store: Any | None = None, order_store: PaymentOrderStoreInterface | None = None,
                 audit_store: Any | None = None) -> None:
        """初始化骨架。

        :param flow_store: 支付流水存储（PaymentFlowStoreInterface，§5.2）；None 时跳过流水落库（降级）
        :param order_store: 本地支付订单存储（PaymentOrderStoreInterface，§4.2/§5.5）；None 时跳过本地幂等/校验（降级）
        :param audit_store: 支付审计存储（PaymentAuditStoreInterface，§8.3）；None 时跳过审计（业务不注入默认关闭）
        """
        self._flow_store = flow_store
        self._order_store = order_store
        self._audit_store = audit_store

    # ------------------------------------------------------------------
    # final 入口（不可覆写，规范 §3.1 红线）
    # ------------------------------------------------------------------

    @final
    async def prepay(self, request: PaymentPrepayRequest) -> PaymentPrepayResponse:
        """下单骨架：幂等检查（§4.2）→ 渠道特有下单 → 三态收敛（未知态走查单兜底，§7）。

        下单本身不产生资金流水（§5.2 流水承载资金变更）；结果未知（网络/超时）抛渠道错误，
        由业务先查单确认再决策（禁止盲目重试，§7.2）。
        """
        await self._check_idempotency(request.out_trade_no)
        try:
            result = await self._do_prepay(request)
        except Exception as exc:
            record_prepay(self._channel_name(), False)
            await self._audit("prepay", request.out_trade_no, request.total_amount, "failed", detail=str(exc))
            raise
        record_prepay(self._channel_name(), True)
        await self._audit("prepay", request.out_trade_no, request.total_amount, "success")
        # 下单成功后写本地支付订单（§4.2/§5.5）：回调校验/关单确认/掉单补偿依赖本地记录；
        # 注入 order_store 时落库（业务生产以本地支付订单表为准，同事务写入）
        if self._order_store is not None:
            await self._order_store.save(PaymentLocalOrder(
                out_trade_no=request.out_trade_no,
                amount=request.total_amount,
                status=PaymentStatus.NOTPAY,
                attach=request.attach or "",
                expire_at=request.time_expire,
            ))
        return result

    @final
    async def refund(self, request: PaymentRefundRequest) -> PaymentRefundResponse:
        """退款骨架：幂等检查（out_refund_no，§5.3）→ 渠道特有退款 → 三态收敛 → 退款申请流水。

        本地只记退款申请（PENDING 待入账，§5.3：渠道退款回调成功后才本地入账）。
        """
        if not self._supports("refund"):
            raise PaymentErrorCode.PAY_CAPABILITY_UNSUPPORTED.to_exception(message="该渠道未声明 refund 能力")
        await self._check_refund_idempotency(request.out_refund_no, request.out_trade_no, request.refund_amount)
        try:
            result = await self._do_refund(request)
        except Exception as exc:
            record_refund(self._channel_name(), "error")
            await self._audit("refund", request.out_trade_no, request.refund_amount, "failed",
                              transaction_id=request.out_refund_no, detail=str(exc))
            raise
        record_refund(self._channel_name(), "success")
        await self._audit("refund", request.out_trade_no, request.refund_amount, "success",
                          transaction_id=request.out_refund_no)
        await self._persist_flow(PaymentFlowContext(
            out_trade_no=request.out_trade_no,
            out_refund_no=request.out_refund_no,
            amount=request.refund_amount,
            event_type=PaymentFlowEvent.REFUND.value,
            status=UNKNOWN,  # 退款申请：终态由渠道回调/查退款收敛（§5.3）
            status_override=PaymentFlowStatus.PENDING,
        ))
        return result

    @final
    async def close_order(self, out_trade_no: str) -> None:
        """关单骨架（§5.5）：本地幂等（已 CLOSED 直接返回、已 SUCCESS 抛冲突）→ 查单确认未支付
        → 渠道特有关单 → 关单流水落库。查单失败禁止强行关单（防已支付被关闭）。
        """
        local = await self._get_local_order(out_trade_no)
        if local is not None:
            if local.status == PaymentStatus.CLOSED:
                return  # 关单幂等：已关闭直接返回原结果
            if local.status == PaymentStatus.SUCCESS:
                raise PaymentErrorCode.PAY_ORDER_STATE_CONFLICT.to_exception(message="已支付订单禁止关单（§5.5）")
        # 查单确认渠道未支付（查单失败异常向上传播，调用方捕获后跳过，禁止状态不明时强行关单）
        order = await self._do_query_order(out_trade_no)
        if order is not None and order.status == PaymentStatus.SUCCESS:
            raise PaymentErrorCode.PAY_ORDER_STATE_CONFLICT.to_exception(message="已支付订单禁止关单（§5.5）")
        await self._do_close_order(out_trade_no)
        await self._audit("close_order", out_trade_no, None, "success")
        await self._persist_flow(PaymentFlowContext(
            out_trade_no=out_trade_no,
            event_type=PaymentFlowEvent.CLOSE.value,
            status=SUCCESS,
            status_override=PaymentFlowStatus.CLOSED,
        ))

    @final
    async def handle_callback(self, headers: Mapping[str, str], body: str) -> None:
        """回调入账骨架（被动入口，§2.3/§4.3）：渠道层验签解密 → 通用层校验（时间戳/幂等/金额/
        attach/状态机）→ 本地事务入账（订单状态 + 支付流水，§5.1）。

        验签/解密失败抛 E3-PAY-001（回调入口映射 401，渠道重试）；
        业务校验失败（金额不符/状态冲突）抛 E4-PAY-*（映射 500/409）。
        """
        start = time.perf_counter()
        try:
            callback = await self._parse_callback(headers, body)
            if callback is None:
                raise PaymentErrorCode.PAY_SIGN_VERIFY_FAILED.to_exception(message="回调验签/解密失败")
            await self._verify_and_check(callback)
            # 渠道事件 → 流水事件类型（支付成功 → PAY，退款成功 → REFUND）
            event = self._callback_event(callback)
            flow_event = PaymentFlowEvent.PAY if event == PaymentEvent.PAY_SUCCESS else PaymentFlowEvent.REFUND
            await self._persist_flow(PaymentFlowContext(
                out_trade_no=callback.out_trade_no,
                amount=callback.amount,
                event_type=flow_event.value,
                status=SUCCESS,
                transaction_id=callback.transaction_id or "",
                raw=callback.raw,
                out_refund_no=callback.mch_refund_no or "",
            ))
        except Exception as exc:  # noqa: BLE001 - 回调结果分类埋点（§11.1）
            if isinstance(exc, WebInfraException) and exc.code == PaymentErrorCode.PAY_SIGN_VERIFY_FAILED.code:
                record_callback(self._channel_name(), "verify_failed")
                await self._audit("callback", "", None, "verify_failed", detail=str(exc), raw=body)
            else:
                record_callback(self._channel_name(), "biz_error")
                await self._audit("callback", "", None, "biz_error", detail=str(exc))
            raise
        record_callback(self._channel_name(), "success", time.perf_counter() - start)
        await self._audit("callback", callback.out_trade_no, callback.amount, "success",
                          transaction_id=callback.transaction_id or "", raw=callback.raw)

    @final
    async def validate_callback(self, callback: PaymentCallback) -> PaymentCallback:
        """业务回调入口通用校验（§4.3/§4.5）：金额/attach 校验 + 支付状态机流转 + 订单状态持久化。

        供已验签的业务回调入口复用（回调经渠道层 _parse_callback 或渠道侧验签组件解密后，
        本方法完成业务层校验与状态收敛）；校验失败抛 E4-PAY-*（金额 E4-PAY-002 / 状态冲突
        E4-PAY-003），调用方映射 4xx 响应。校验通过返回原回调，供业务处理器分发。
        """
        await self._verify_and_check(callback)
        return callback

    # ------------------------------------------------------------------
    # 必选能力：抽象方法（漏实现无法实例化，规范 §3.2 加载期失败）
    # ------------------------------------------------------------------

    @abstractmethod
    async def _do_prepay(self, request: PaymentPrepayRequest) -> PaymentPrepayResponse:
        """渠道特有下单逻辑，由渠道实现方填充；骨架流程 prepay 为 final 不可覆写"""

    @abstractmethod
    async def _do_query_order(self, out_trade_no: str) -> Any:
        """渠道特有查单逻辑（掉单补偿/关单确认依赖，规范 §3.2/§3.4）"""

    @abstractmethod
    async def _do_close_order(self, out_trade_no: str) -> None:
        """渠道特有关单逻辑，由渠道实现方填充；骨架流程 close_order 为 final 不可覆写"""

    @abstractmethod
    async def _parse_callback(self, headers: Mapping[str, str], body: str) -> PaymentCallback | None:
        """渠道特有回调验签解密（渠道层，规范 §2.3/附录 B.2），由渠道实现方填充；失败返回 None"""

    # ------------------------------------------------------------------
    # 可选能力：普通方法 + 默认抛 E4-PAY-008（未声明能力被调用，规范 §3.1/§3.4）
    # ------------------------------------------------------------------

    async def _do_refund(self, request: PaymentRefundRequest) -> PaymentRefundResponse:
        """渠道特有退款逻辑；声明 refund 能力的渠道须覆写（默认不支持）"""
        raise PaymentErrorCode.PAY_CAPABILITY_UNSUPPORTED.to_exception(message="该渠道未声明 refund 能力")

    async def _do_query_refund(self, out_refund_no: str) -> Any:
        """渠道特有查退款逻辑（refund 配套能力，规范 §3.4）；声明 query_refund 的渠道须覆写"""
        raise PaymentErrorCode.PAY_CAPABILITY_UNSUPPORTED.to_exception(message="该渠道未声明 query_refund 能力")

    # ------------------------------------------------------------------
    # 骨架内部方法：final，禁止渠道实现方覆写（规范 §3.1）
    # ------------------------------------------------------------------

    @final
    async def _check_idempotency(self, out_trade_no: str) -> None:
        """下单前本地幂等检查（§4.2）：已 SUCCESS/进行中拒绝，已 CLOSED 允许重新下单（新单号）"""
        local = await self._get_local_order(out_trade_no)
        if local is None:
            return
        if local.status in (PaymentStatus.SUCCESS, PaymentStatus.USERPAYING, PaymentStatus.EXCEPTION):
            raise PaymentErrorCode.PAY_ORDER_STATE_CONFLICT.to_exception(
                message=f"订单状态不允许下单: {local.status.value}（规范 §4.2）"
            )

    @final
    async def _check_refund_idempotency(self, out_refund_no: str, out_trade_no: str | None = None,
                                        refund_amount: Decimal | None = None) -> None:
        """退款幂等与超额校验（§5.3）：同 out_refund_no 已存在退款申请 → 拒绝重复申请；
        部分退款累计（已退 + 本次 ≤ 实付金额）超限 → 拒绝。"""
        if self._flow_store is None:
            return
        existing = await self._flow_store.find_by_order_and_event(out_refund_no, PaymentFlowEvent.REFUND)
        if existing is not None:
            raise PaymentErrorCode.PAY_ORDER_STATE_CONFLICT.to_exception(message="退款单已申请，禁止重复申请（§5.3）")
        # 部分退款累计约束（§5.3）：已退金额 + 本次退款 ≤ 实付金额
        if out_trade_no and refund_amount is not None:
            local = await self._get_local_order(out_trade_no)
            if local is not None:
                already = await self._flow_store.sum_refunded(out_trade_no)
                if already + refund_amount > local.amount:
                    raise CommonErrorCode.COMMON_CONFLICT.to_exception(
                        message=f"退款金额超实付金额（已退 {already} + 本次 {refund_amount} > 实付 {local.amount}，§5.3）"
                    )

    @final
    async def _get_local_order(self, out_trade_no: str) -> PaymentLocalOrder | None:
        """查本地订单状态（关单幂等/下单幂等判断，§5.5/§4.2）"""
        if self._order_store is None:
            return None
        return await self._order_store.find_by_out_trade_no(out_trade_no)

    @final
    async def _verify_and_check(self, callback: PaymentCallback) -> None:
        """通用层业务校验（§4.3）：金额比对（E4-PAY-002）/ attach 关联 / 状态机幂等流转（E4-PAY-003）。

        时间戳容差/重放校验由渠道层 _parse_callback 完成（§2.3 职责分离）。
        """
        if self._order_store is None:
            logger.warning("支付回调未注入 order_store，跳过金额/attach/状态机校验（降级）")
            return
        local = await self._order_store.find_by_out_trade_no(callback.out_trade_no)
        if local is None:
            raise PaymentErrorCode.PAY_ORDER_STATE_CONFLICT.to_exception(message=f"回调订单不存在: {callback.out_trade_no}")
        # 金额强校验（§4.3）：回调金额必须与本地订单金额一致
        if callback.amount != local.amount:
            raise PaymentErrorCode.PAY_AMOUNT_MISMATCH.to_exception(
                message=f"回调金额 {callback.amount} 与订单金额 {local.amount} 不符（§4.3）"
            )
        # attach 关联校验（§4.3）：回调 attach 与本地订单一致（本地未设 attach 时不强制）
        if callback.attach and local.attach and callback.attach != local.attach:
            raise PaymentErrorCode.PAY_AMOUNT_MISMATCH.to_exception(message="回调 attach 与订单关联标识不符（§4.3）")
        # 状态机幂等流转（§4.5）：按回调事件收敛状态
        event = self._callback_event(callback)
        new_status = PaymentStateMachine.target(local.status, event)
        await self._order_store.update_status(callback.out_trade_no, new_status)

    @final
    async def _persist_flow(self, context: PaymentFlowContext) -> None:
        """流水落库（§5.2 本地事务表）：按 context 三态收敛写支付流水（幂等：唯一索引兜底，§4.3）。

        未注入 flow_store 时降级（仅日志），资金链路强一致需业务注入本地事务表实现。
        """
        if self._flow_store is None:
            logger.warning("支付流水未注入 flow_store，跳过流水落库（降级）：out_trade_no=%s event=%s", context.out_trade_no, context.event_type)
            return
        status = context.status_override or (PaymentFlowStatus.BOOKED if context.status == SUCCESS else PaymentFlowStatus.PENDING)
        record = PaymentFlowRecord(
            out_trade_no=context.out_trade_no,
            out_refund_no=context.out_refund_no,
            event_type=PaymentFlowEvent(context.event_type),
            amount=context.amount or Decimal("0"),
            status=status,
            channel=context.channel,
            transaction_id=context.transaction_id,
            raw=context.raw or {},
            is_reversal=context.is_reversal,
            original_flow_id=context.original_flow_id,
        )
        await self._flow_store.append(record)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @final
    def _supports(self, capability: str) -> bool:
        """能力位校验（§3.4）：调用未声明能力返回 E4-PAY-008（禁止透传渠道）"""
        if not self.capabilities:
            logger.warning("渠道未声明 capabilities，能力校验放行（建议声明，规范 §3.4）")
            return True
        return capability in self.capabilities

    @final
    def _channel_name(self) -> str:
        """指标渠道标签（低基数：渠道类名）"""
        return self.__class__.__name__

    @final
    async def _audit(self, action: str, out_trade_no: str, amount: Decimal | None,
                     result: str, *, transaction_id: str = "", detail: str = "",
                     raw: dict | object | None = None) -> None:
        """支付审计埋点（§8.3）：成功/失败均留痕；审计失败仅记日志不阻断业务主链路。

        :param action: 动作（prepay/callback/refund/close_order）
        :param out_trade_no: 商户订单号
        :param amount: 金额（元，字符串落审计避免精度丢失）
        :param result: 结果（success/failed/verify_failed/biz_error，失败同样留痕）
        :param transaction_id: 渠道交易号/退款单号
        :param detail: 补充说明（错误信息，脱敏后）
        :param raw: 渠道原始报文（§8.6 只落审计存储，不落业务日志）
        """
        if self._audit_store is None:
            return
        try:
            from web_infra.payment.payment_audit_store import PaymentAuditRecord

            await self._audit_store.append(PaymentAuditRecord(
                action=action, out_trade_no=out_trade_no,
                amount=f"{amount:.2f}" if amount is not None else "",
                channel=self._channel_name(), result=result,
                transaction_id=transaction_id, detail=detail,
                raw=raw if isinstance(raw, dict) else {"body": str(raw)} if raw is not None else {},
            ))
        except Exception:  # noqa: BLE001 - 审计失败不阻断业务主链路（§8.3 审计属旁路留痕）
            logger.warning("payment_audit_failed action=%s out_trade_no=%s result=%s", action, out_trade_no, result)

    @staticmethod
    def _callback_event(callback: PaymentCallback) -> PaymentEvent:
        """回调事件 → 状态机事件（支付成功回调 → PAY_SUCCESS；退款回调 → 对应事件）"""
        if callback.event_type in ("TRANSACTION.SUCCESS", "PAY.SUCCESS"):
            return PaymentEvent.PAY_SUCCESS
        if callback.event_type in ("REFUND.SUCCESS",):
            return PaymentEvent.REFUND_SUCCESS
        raise PaymentErrorCode.PAY_ORDER_STATE_CONFLICT.to_exception(message=f"未知回调事件类型: {callback.event_type}")
