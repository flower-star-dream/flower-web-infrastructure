"""
支付下单请求模型

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 统一支付下单请求结构（屏蔽渠道差异，金额统一 Decimal 元）。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from web_infra.capabilities.payment.payment_scene import PaymentScene


class PaymentPrepayRequest(BaseModel):
    """支付下单请求"""

    scene: PaymentScene = Field(description="支付场景（JSAPI/NATIVE/H5/APP）")
    out_trade_no: str = Field(description="商户订单号（渠道侧唯一，下单幂等键）")
    description: str = Field(description="商品描述")
    total_amount: Decimal = Field(gt=0, description="订单总金额（元，最多两位小数，必须大于 0）")
    notify_url: str | None = Field(default=None, description="支付结果回调地址（缺省用渠道配置）")
    openid: str | None = Field(default=None, description="微信用户 openid（JSAPI 必填）")
    client_ip: str | None = Field(default=None, description="用户终端 IP（H5 必填）")
    time_expire: datetime | None = Field(default=None, description="订单失效时间（渠道侧 ISO8601）")
    attach: str | None = Field(default=None, description="商户附加数据（回调原样返回，用于业务标识）")
