"""
OAuth2 客户端

@Author: 花海
@Date: 2026/08/14 20:00
@Description: OAuth2 客户端模型（规范 §6.1/§6.2：client_id 标识客户端，client_secret 凭证校验；
              授权码模式端点预留 redirect_uris）。最小实现聚焦令牌签发/校验。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OAuth2Client:
    """OAuth2 客户端（客户端注册信息）"""

    client_id: str  # 客户端标识（设备类型如 web/ios/android，规范 §6.2）
    client_secret: str  # 客户端密钥（服务端保存，禁止明文入库）
    scopes: tuple[str, ...] = field(default_factory=tuple)  # 客户端可用权限范围（§6.6 Scope）
    grant_types: tuple[str, ...] = ("client_credentials",)  # 授权类型（授权码模式预留）
    redirect_uris: tuple[str, ...] = field(default_factory=tuple)  # 回调地址（授权码模式预留）
