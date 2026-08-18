"""
支付场景枚举

@Author: 花海
@Date: 2026/08/16 10:00
@Description: 支付场景枚举（对齐微信支付 APIv3 下单场景：JSAPI/Native/H5/App）。
"""
from __future__ import annotations

from enum import Enum


class PaymentScene(str, Enum):
    """支付场景枚举"""

    JSAPI = "JSAPI"
    NATIVE = "NATIVE"
    H5 = "H5"
    APP = "APP"
