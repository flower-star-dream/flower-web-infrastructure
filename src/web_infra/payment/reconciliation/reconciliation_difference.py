"""
对账差异模型与分类（ReconciliationDifference）

@Author: 花海
@Date: 2026/08/17
@Description: 对账差异（规范 §6.3 差异分类与判定）：五类差异（本地有渠道无 / 渠道有本地无 /
              金额不一致 / 状态不一致 / 退款差异）+ 风险等级（中/高/极高），
              差异进入处理队列（自动处理：查单确认后补记/冲正，§6.4；金额不一致强制人工）。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from web_infra.payment.payment_flow_status import PaymentFlowEvent


class DifferenceType(str, Enum):
    """对账差异类型（规范 §6.3 五类）"""

    LOCAL_ONLY = "LOCAL_ONLY"        # 本地有、渠道无（短款风险：可能回调伪造/本地误入账）
    CHANNEL_ONLY = "CHANNEL_ONLY"    # 渠道有、本地无（长款风险：回调丢失/漏入账/资金滞留渠道）
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"  # 金额不一致（资金异常，冻结挂账 + P0 告警 + 人工）
    STATUS_MISMATCH = "STATUS_MISMATCH"  # 状态不一致（异常或篡改，人工核查）
    REFUND_MISMATCH = "REFUND_MISMATCH"  # 退款差异（资金流出，优先处理）


class DifferenceSeverity(str, Enum):
    """差异风险等级（规范 §6.3）"""

    MEDIUM = "MEDIUM"  # 中：本地有渠道无
    HIGH = "HIGH"      # 高：渠道有本地无 / 状态不一致 / 退款差异
    CRITICAL = "CRITICAL"  # 极高：金额不一致（立即冻结/挂账）


# 差异类型 → 风险等级映射（§6.3 判定表）
DIFFERENCE_SEVERITY: dict[DifferenceType, DifferenceSeverity] = {
    DifferenceType.LOCAL_ONLY: DifferenceSeverity.MEDIUM,
    DifferenceType.CHANNEL_ONLY: DifferenceSeverity.HIGH,
    DifferenceType.AMOUNT_MISMATCH: DifferenceSeverity.CRITICAL,
    DifferenceType.STATUS_MISMATCH: DifferenceSeverity.HIGH,
    DifferenceType.REFUND_MISMATCH: DifferenceSeverity.HIGH,
}

# 金额不一致等人工强制类型（§6.4：禁止自动动账）
MANUAL_ONLY_TYPES = frozenset({DifferenceType.AMOUNT_MISMATCH, DifferenceType.STATUS_MISMATCH})


@dataclass
class ReconciliationDifference:
    """单条对账差异（对齐键 + 差异类型 + 双方快照 + 处理状态）"""

    diff_type: DifferenceType  # 差异类型（§6.3）
    out_trade_no: str  # 商户订单号（对齐键）
    event_type: PaymentFlowEvent  # 交易事件类型
    local_amount: Decimal | None = None  # 本地流水金额（本地有渠道无 / 金额不一致时非空）
    channel_amount: Decimal | None = None  # 渠道账单金额（渠道有本地无 / 金额不一致时非空）
    local_status: str = ""  # 本地流水状态
    channel_status: str = ""  # 渠道账单状态
    out_refund_no: str = ""  # 退款单号（退款差异非空）
    channel_transaction_id: str = ""  # 渠道交易号
    severity: DifferenceSeverity = DifferenceSeverity.MEDIUM  # 风险等级
    action: str = "待处理"  # 处理动作（§6.4：查单补记/查单冲正/挂账人工/P0 告警）
    handled: bool = False  # 是否已处理（人工处理后回填，审计留痕 §6.6）

    def __post_init__(self) -> None:
        """差异等级按类型自动收敛（§6.3 判定表）"""
        self.severity = DIFFERENCE_SEVERITY[self.diff_type]
