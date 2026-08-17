"""
支付测试工具包

@Author: 花海
@Date: 2026/08/16
@Description: 支付链路测试组件（规范 §10.3）：回调模拟器（构造回调报文）与渠道契约测试
              套件（任意骨架实现复用同一契约断言）。仅测试/联调使用，不参与生产装配。
"""
from web_infra.payment.testing.payment_callback_simulator import PaymentCallbackSimulator
from web_infra.payment.testing.payment_channel_contract import PaymentChannelContract

__all__ = ["PaymentCallbackSimulator", "PaymentChannelContract"]
