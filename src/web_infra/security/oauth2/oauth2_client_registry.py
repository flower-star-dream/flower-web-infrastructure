"""
OAuth2 客户端注册表

@Author: 花海
@Date: 2026/08/14 20:00
@Description: OAuth2 客户端注册与校验（规范 §6.1/§6.2 客户端接入管理）。
              注册表抽象 + 内存默认实现；多实例/持久化场景可扩展数据库实现。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from web_infra.security.oauth2.oauth2_client import OAuth2Client


@runtime_checkable
class OAuth2ClientRegistry(Protocol):
    """OAuth2 客户端注册表抽象接口"""

    def register(self, client: OAuth2Client) -> None:
        """注册客户端"""
        ...

    def get(self, client_id: str) -> OAuth2Client | None:
        """按 client_id 查询客户端"""
        ...


class InMemoryOAuth2ClientRegistry:
    """内存 OAuth2 客户端注册表（默认实现）"""

    def __init__(self) -> None:
        self._clients: dict[str, OAuth2Client] = {}

    def register(self, client: OAuth2Client) -> None:
        """注册客户端（重复 client_id 覆盖）"""
        self._clients[client.client_id] = client

    def get(self, client_id: str) -> OAuth2Client | None:
        """按 client_id 查询客户端"""
        return self._clients.get(client_id)

    def contains(self, client_id: str) -> bool:
        """判断客户端是否已注册"""
        return client_id in self._clients
