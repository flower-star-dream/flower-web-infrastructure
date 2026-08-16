"""
支付下单结果模型

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 统一支付下单结果（按场景返回 prepay_id/调起参数/code_url/h5_url）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from web_infra.payment.payment_scene import PaymentScene


class PaymentPrepayResponse(BaseModel):
    """支付下单结果"""

    scene: PaymentScene = Field(description="支付场景")
    prepay_id: str | None = Field(default=None, description="预支付 ID（JSAPI/App 场景）")
    pay_params: dict | None = Field(default=None, description="调起支付参数（JSAPI/App 场景）")
    code_url: str | None = Field(default=None, description="二维码内容（Native 场景）")
    h5_url: str | None = Field(default=None, description="跳转收银台链接（H5 场景）")
    channel_order_id: str | None = Field(default=None, description="渠道交易号（下单即返回时填充，通常为空）")
