"""
支付回调业务处理器接口

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 支付回调业务处理器 SPI（业务实现）：处理支付成功/退款结果回调。
              回调幂等由业务保证（回调事件有 event_type+out_trade_no，可复用框架幂等组件）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from web_infra.capabilities.payment.payment_callback import PaymentCallback


class PaymentCallbackHandler(ABC):
    """支付回调业务处理器（业务 SPI，无默认实现）"""

    @abstractmethod
    async def handle(self, callback: PaymentCallback) -> None:
        """处理一条支付/退款回调（业务内保证幂等）"""
        ...
