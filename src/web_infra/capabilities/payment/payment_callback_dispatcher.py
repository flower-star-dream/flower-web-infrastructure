"""
支付回调分发器

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 支付回调分发器：将验签解密后的统一回调分发给已注册的业务处理器。
              未注册任何处理器时静默兜底（日志告警），保证回调入口不抛错。
"""
from __future__ import annotations

import logging

from web_infra.capabilities.payment.payment_callback import PaymentCallback
from web_infra.capabilities.payment.payment_callback_handler_interface import PaymentCallbackHandler

logger = logging.getLogger("web_infra.capabilities.payment.dispatcher")


class PaymentCallbackDispatcher:
    """支付回调分发器（注册式装配业务处理器）"""

    def __init__(self) -> None:
        self._handlers: list[PaymentCallbackHandler] = []

    def register(self, handler: PaymentCallbackHandler) -> None:
        """注册回调处理器"""
        self._handlers.append(handler)

    def unregister(self, handler: PaymentCallbackHandler) -> None:
        """注销回调处理器"""
        if handler in self._handlers:
            self._handlers.remove(handler)

    async def dispatch(self, callback: PaymentCallback) -> None:
        """将回调分发给全部已注册处理器（顺序执行）"""
        if not self._handlers:
            logger.warning("支付回调无处理器，回调被忽略 event_type=%s out_trade_no=%s", callback.event_type, callback.out_trade_no)
            return
        for handler in self._handlers:
            await handler.handle(callback)
