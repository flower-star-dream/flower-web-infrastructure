"""
支付模块

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 支付 SPI 与微信渠道实现聚合导出：统一回调结构、三件 SPI、内存默认实现、
              回调分发器、渠道注册表、渠道骨架（§3.1）、支付流水/状态机/超时关单、
              冲正（§7.5）、支付审计（§8.3）、支付权限点（§8.4）。
              微信渠道实现经子模块路径引用（web_infra.payment.provider.wechat）；
              对账机制（§6）与风控限额（§9）经 web_infra.payment.reconciliation / risk 子包导出。
"""
from web_infra.payment.in_memory_payment_callback_verifier import InMemoryPaymentCallbackVerifier
from web_infra.payment.in_memory_payment_flow_store import InMemoryPaymentFlowStore
from web_infra.payment.in_memory_payment_gateway import InMemoryPaymentGateway
from web_infra.payment.in_memory_payment_order_store import InMemoryPaymentOrderStore
from web_infra.payment.payment_audit_store import (
    InMemoryPaymentAuditStore,
    PaymentAuditRecord,
    PaymentAuditStoreInterface,
)
from web_infra.payment.payment_callback import PaymentCallback
from web_infra.payment.payment_callback_dispatcher import PaymentCallbackDispatcher
from web_infra.payment.payment_callback_handler_interface import PaymentCallbackHandler
from web_infra.payment.payment_callback_verifier_interface import PaymentCallbackVerifier
from web_infra.payment.payment_channel_template import PaymentChannelTemplate
from web_infra.payment.payment_config import PaymentConfig, WechatPayConfig
from web_infra.payment.payment_constant import PaymentConstant
from web_infra.payment.payment_error_code import PaymentErrorCode, PaymentErrorCodeEnum
from web_infra.payment.payment_flow_record import PaymentFlowRecord
from web_infra.payment.payment_flow_status import PaymentFlowEvent, PaymentFlowStatus
from web_infra.payment.payment_flow_store_interface import PaymentFlowStoreInterface
from web_infra.payment.payment_gateway_interface import PaymentGateway
from web_infra.payment.payment_gateway_registry import PaymentGatewayRegistry
from web_infra.payment.payment_order import PaymentOrder
from web_infra.payment.payment_order_store_interface import PaymentLocalOrder, PaymentOrderStoreInterface
from web_infra.payment.payment_permission import PaymentPermission
from web_infra.payment.payment_reversal import reversal_flow
from web_infra.payment.payment_scene import PaymentScene
from web_infra.payment.payment_state_machine import PaymentStateMachine
from web_infra.payment.payment_status import PaymentEvent, PaymentStatus, RefundStatus
from web_infra.payment.prepay_request import PaymentPrepayRequest
from web_infra.payment.prepay_response import PaymentPrepayResponse
from web_infra.payment.refund_request import PaymentRefundRequest
from web_infra.payment.refund_response import PaymentRefundResponse
from web_infra.payment.reconciliation import (
    BillFileManager,
    BillRecord,
    InMemoryReconciliationAuditStore,
    ReconciliationAuditRecord,
    ReconciliationAuditStoreInterface,
    ReconciliationDifference,
    ReconciliationResult,
    ReconciliationService,
    run_reconciliation,
)
from web_infra.payment.risk import (
    InMemoryLimitCounterStore,
    LimitCounterStoreInterface,
    LimitRule,
    PaymentLimitConfig,
    PaymentRiskGuard,
)

__all__ = [
    "PaymentGateway",
    "PaymentCallbackVerifier",
    "PaymentCallbackHandler",
    "PaymentCallbackDispatcher",
    "PaymentGatewayRegistry",
    "InMemoryPaymentGateway",
    "InMemoryPaymentCallbackVerifier",
    "PaymentChannelTemplate",
    "PaymentFlowRecord",
    "PaymentFlowStatus",
    "PaymentFlowEvent",
    "PaymentFlowStoreInterface",
    "InMemoryPaymentFlowStore",
    "PaymentLocalOrder",
    "PaymentOrderStoreInterface",
    "InMemoryPaymentOrderStore",
    "PaymentStateMachine",
    "PaymentPrepayRequest",
    "PaymentPrepayResponse",
    "PaymentOrder",
    "PaymentRefundRequest",
    "PaymentRefundResponse",
    "PaymentCallback",
    "PaymentScene",
    "PaymentStatus",
    "PaymentEvent",
    "RefundStatus",
    "PaymentConstant",
    "PaymentErrorCode",
    "PaymentErrorCodeEnum",
    "PaymentConfig",
    "WechatPayConfig",
    "reversal_flow",
    "PaymentAuditRecord",
    "PaymentAuditStoreInterface",
    "InMemoryPaymentAuditStore",
    "PaymentPermission",
    "BillRecord",
    "BillFileManager",
    "ReconciliationDifference",
    "ReconciliationResult",
    "ReconciliationService",
    "ReconciliationAuditRecord",
    "ReconciliationAuditStoreInterface",
    "InMemoryReconciliationAuditStore",
    "run_reconciliation",
    "LimitRule",
    "PaymentLimitConfig",
    "LimitCounterStoreInterface",
    "InMemoryLimitCounterStore",
    "PaymentRiskGuard",
]

