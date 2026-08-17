"""
本地支付订单模型与存储接口（SPI）

@Author: 花海
@Date: 2026/08/16
@Description: 骨架层依赖的本地支付订单存取（规范 §3.1 内部方法 _get_local_order）：
              PaymentLocalOrder 为业务支付订单的支付子集（订单号/金额/状态/attach），
              PaymentOrderStoreInterface 由业务实现（业务订单表适配），
              支撑骨架的幂等检查（§4.2）、关单前查单确认（§5.5）、回调金额/attach 校验（§4.3）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from web_infra.payment.payment_status import PaymentStatus


@dataclass
class PaymentLocalOrder:
    """本地支付订单（业务订单的支付子集视图）"""

    out_trade_no: str  # 商户订单号
    amount: Decimal  # 订单金额（元，服务端取价，§8.5）
    status: PaymentStatus = PaymentStatus.NOTPAY  # 支付状态（§4.5 状态机）
    attach: str = ""  # 附加数据（回调关联校验，§4.3）
    expire_at: datetime | None = None  # 本地失效时间（与渠道 time_expire 一致，§5.5）
    extra: dict = field(default_factory=dict)  # 业务扩展字段（透传，不参与框架校验）


@runtime_checkable
class PaymentOrderStoreInterface(Protocol):
    """本地支付订单存储抽象接口（业务实现：订单表适配 SPI）"""

    async def find_by_out_trade_no(self, out_trade_no: str) -> PaymentLocalOrder | None:
        """按商户订单号查本地订单；不存在返回 None"""
        ...

    async def save(self, order: PaymentLocalOrder, session: object | None = None) -> PaymentLocalOrder:
        """保存/更新本地订单（传 session 时与业务同事务提交）"""
        ...

    async def update_status(self, out_trade_no: str, status: PaymentStatus, session: object | None = None) -> bool:
        """更新订单支付状态（返回是否更新成功）"""
        ...

    async def find_expired(self, expire_before: datetime, limit: int = 100) -> list[PaymentLocalOrder]:
        """查超时未支付订单（§5.5 定时关单扫描依据）"""
        ...
