"""
内存本地支付订单存储

@Author: 花海
@Date: 2026/08/16
@Description: PaymentOrderStoreInterface 内存默认实现（单实例/测试；生产由业务订单表适配）。
"""
from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Any

from web_infra.capabilities.payment.payment_order_store_interface import PaymentLocalOrder
from web_infra.capabilities.payment.payment_status import PaymentStatus


class InMemoryPaymentOrderStore:
    """内存本地支付订单存储（默认实现）"""

    def __init__(self) -> None:
        self._orders: dict[str, PaymentLocalOrder] = {}
        self._lock = RLock()

    async def find_by_out_trade_no(self, out_trade_no: str) -> PaymentLocalOrder | None:
        """按商户订单号查本地订单"""
        with self._lock:
            return self._orders.get(out_trade_no)

    async def save(self, order: PaymentLocalOrder, session: Any | None = None) -> PaymentLocalOrder:
        """保存/更新本地订单"""
        with self._lock:
            self._orders[order.out_trade_no] = order
            return order

    async def update_status(self, out_trade_no: str, status: PaymentStatus, session: Any | None = None) -> bool:
        """更新订单支付状态"""
        with self._lock:
            order = self._orders.get(out_trade_no)
            if order is None:
                return False
            order.status = status
            return True

    async def find_expired(self, expire_before: datetime, limit: int = 100) -> list[PaymentLocalOrder]:
        """查超时未支付订单（§5.5 定时关单扫描依据：未支付且失效时间已到）"""
        with self._lock:
            expired = [
                order
                for order in self._orders.values()
                if order.status == PaymentStatus.NOTPAY
                and order.expire_at is not None
                and order.expire_at < expire_before
            ]
            return expired[:limit]
