"""
支付模块导出冒烟测试

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 支付为可选能力（2026-08-17）：不随 web_infra 顶层导出，需显式从
              web_infra.capabilities.payment 引入；本测试覆盖"顶层不导出 + 子模块完整导出"的契约。
"""
import importlib

import pytest


def test_top_level_not_exported():
    """支付能力不随 web_infra 顶层导出（需主动引入）"""
    web_infra = importlib.import_module("web_infra")
    assert not hasattr(web_infra, "PaymentGateway")
    assert not hasattr(web_infra, "PaymentCallback")
    assert not hasattr(web_infra, "PaymentGatewayRegistry")
    # 顶层 from import 应直接失败，防止误用
    with pytest.raises(ImportError):
        from web_infra import PaymentGateway  # noqa: F401


def test_payment_submodule_exports():
    """web_infra.capabilities.payment 子模块完整导出（显式引入可用）"""
    from web_infra.capabilities.payment import (
        InMemoryPaymentGateway,
        PaymentGateway,
        PaymentGatewayRegistry,
        PaymentScene,
        PaymentStatus,
        WechatPayConfig,
    )

    assert PaymentGateway is not None
    assert PaymentGatewayRegistry is not None
    assert InMemoryPaymentGateway is not None
    assert PaymentScene.JSAPI.value == "JSAPI"
    assert PaymentStatus.SUCCESS.value == "SUCCESS"
    assert WechatPayConfig is not None
