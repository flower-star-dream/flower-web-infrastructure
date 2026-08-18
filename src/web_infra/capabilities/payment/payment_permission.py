"""
支付权限点常量（PaymentPermission）

@Author: 花海
@Date: 2026/08/17
@Description: 支付操作 RBAC 权限点（规范 §8.4 最小权限）：下单/查单/退款/关单/对账/冲正
              按权限点分离（AUTH_PERM_ 前缀，对齐上位 §5.4 常量规范、§6.6 RBAC）。
              退款/冲正/人工补记属高风险操作：独立权限点 + 审批流 + 全量审计（§8.4），
              由业务接入框架 RBAC/审批组件按权限点拦截。
"""
from __future__ import annotations


class PaymentPermission:
    """支付权限点常量（RBAC 授权 key，AUTH_PERM_ 前缀）"""

    AUTH_PERM_PAY_PREPAY = "AUTH_PERM_PAY_PREPAY"  # 发起支付（下单）
    AUTH_PERM_PAY_QUERY = "AUTH_PERM_PAY_QUERY"  # 查单/查退款
    AUTH_PERM_PAY_CLOSE = "AUTH_PERM_PAY_CLOSE"  # 关单（超时关单任务/人工关单）
    AUTH_PERM_PAY_REFUND = "AUTH_PERM_PAY_REFUND"  # 退款（高风险：独立权限点 + 审批，§8.4）
    AUTH_PERM_PAY_REVERSAL = "AUTH_PERM_PAY_REVERSAL"  # 冲正（高风险：独立权限点 + 审批，§8.4）
    AUTH_PERM_PAY_RECONCILE = "AUTH_PERM_PAY_RECONCILE"  # 对账任务/差异处理（含人工补记）
    AUTH_PERM_PAY_BILL = "AUTH_PERM_PAY_BILL"  # 渠道账单文件管理（§6.7 最小权限：仅对账服务可读）
