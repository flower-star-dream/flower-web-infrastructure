"""
对账模块（reconciliation）

@Author: 花海
@Date: 2026/08/17
@Description: 对账机制（规范 §6）：渠道账单统一明细（BillRecord）、差异分类（§6.3）、
              对账服务编排（§6.2/§6.4 自动处理：查单补记/冲正，金额不一致强制人工）、
              对账审计存储（§6.6 只增不改）、T+1 对账任务（§6.5 防重/唯一标识）、
              账单文件管理（§6.7 校验/存储/归档）。
"""
from web_infra.payment.reconciliation.bill_file_manager import BillFileManager
from web_infra.payment.reconciliation.bill_record import BillRecord
from web_infra.payment.reconciliation.reconciliation_audit_store import (
    InMemoryReconciliationAuditStore,
    ReconciliationAuditRecord,
    ReconciliationAuditStoreInterface,
)
from web_infra.payment.reconciliation.reconciliation_difference import (
    DIFFERENCE_SEVERITY,
    MANUAL_ONLY_TYPES,
    DifferenceSeverity,
    DifferenceType,
    ReconciliationDifference,
)
from web_infra.payment.reconciliation.reconciliation_service import ReconciliationResult, ReconciliationService
from web_infra.payment.reconciliation.reconciliation_task import RECONCILE_JOB_ID_TEMPLATE, run_reconciliation

__all__ = [
    "BillRecord",
    "BillFileManager",
    "DifferenceType",
    "DifferenceSeverity",
    "ReconciliationDifference",
    "ReconciliationResult",
    "ReconciliationService",
    "ReconciliationAuditRecord",
    "ReconciliationAuditStoreInterface",
    "InMemoryReconciliationAuditStore",
    "run_reconciliation",
    "RECONCILE_JOB_ID_TEMPLATE",
    "DIFFERENCE_SEVERITY",
    "MANUAL_ONLY_TYPES",
]
