"""
OAuth2 令牌服务

@Author: 花海
@Date: 2026/08/14 20:00
@Description: OAuth2 最小令牌签发与校验（规范 §6.1/§6.2/§6.4/§6.7）：
              - client_credentials 授权类型：客户端凭证校验后签发自包含 access token（JWT）
              - 载荷含 userId/scope/exp（规范 §6.2：载荷只含 userId + scope + exp，敏感信息走独立接口）
              - 复用 JWTUtil 签发/校验（含可选 Redis 状态存储，登出撤销）
              - 资源服务器校验在统一入口完成（配合 AuthMiddleware，§6.4），业务禁止自行解析凭证
"""
from __future__ import annotations

import logging
from typing import Any

from web_infra.infra.error import CommonErrorCode
from web_infra.capabilities.security.jwt_util import JWTUtil
from web_infra.capabilities.security.oauth2.oauth2_client_registry import OAuth2ClientRegistry
from web_infra.capabilities.security.token_verify_status_enum import TokenVerifyStatus

logger = logging.getLogger("web_infra.capabilities.security.oauth2")


class OAuth2TokenService:
    """OAuth2 令牌签发/校验服务（client_credentials 最小实现，授权码端点预留）"""

    TOKEN_TYPE = "Bearer"

    def __init__(self, registry: OAuth2ClientRegistry, *, access_token_ttl_minutes: int = 15) -> None:
        """初始化令牌服务。

        :param registry: 客户端注册表（OAuth2ClientRegistry）
        :param access_token_ttl_minutes: access token 有效期（分钟，规范附录 A.3 默认 15）
        """
        self._registry = registry
        self._access_ttl_minutes = access_token_ttl_minutes

    async def issue_client_token(self, client_id: str, client_secret: str, scopes: list[str] | None = None) -> dict[str, Any]:
        """客户端凭证授权（client_credentials）：校验客户端 -> 签发 access token。

        :param client_id: 客户端标识
        :param client_secret: 客户端密钥
        :param scopes: 申请的权限范围（缺省用客户端注册范围，规范 §6.6 Scope）
        :return: 令牌响应（access_token / token_type / expires_in）
        :raises BizException: 客户端不存在或密钥错误（E2-AUTH-000）
        """
        client = self._registry.get(client_id)
        if client is None or client.client_secret != client_secret:
            raise CommonErrorCode.AUTH_UNAUTHENTICATED.to_exception(message="OAuth2 客户端认证失败")
        scope = " ".join(scopes) if scopes else " ".join(client.scopes)
        # 规范 §6.3：凭证声明时效与实际 exp 必须一致——签发时显式传入与 expires_in 相同的 TTL（秒），
        # 统一以本服务的 access_token_ttl_minutes（默认 15 分钟）为唯一来源，避免声明与签发不一致
        ttl_seconds = self._access_ttl_minutes * 60
        token = await JWTUtil.generate_token(
            user_id=client_id,
            username=client_id,
            extra_claims={
                "scope": scope,
                "client_id": client_id,
                "token_type": "access",
            },
            expires_in=ttl_seconds,
        )
        return {
            "access_token": token,
            "token_type": self.TOKEN_TYPE,
            "expires_in": ttl_seconds,
        }

    async def verify_token(self, token: str) -> dict[str, Any]:
        """校验 access token（资源服务器统一入口调用，规范 §6.4）。

        :return: 载荷（含 sub/scope/client_id）
        :raises BizException: 凭证过期 E2-AUTH-001 / 非法 E2-AUTH-002
        """
        payload, status = await JWTUtil.verify_token(token)
        if status == TokenVerifyStatus.EXPIRED:
            raise CommonErrorCode.AUTH_EXPIRED.to_exception(message="OAuth2 凭证已过期")
        # 即将过期（EXPIRING）与有效一致放行：规范 §6.1 静默刷新，凭证本身未过期，不应拒绝
        if status not in (TokenVerifyStatus.VALID, TokenVerifyStatus.EXPIRING):
            raise CommonErrorCode.AUTH_INVALID.to_exception(message="OAuth2 凭证非法或已被撤销")
        if payload is None:
            raise CommonErrorCode.AUTH_INVALID.to_exception(message="OAuth2 凭证非法或已被撤销")
        return payload

    async def invalidate_token(self, token: str) -> bool:
        """撤销 access token（登出/客户端吊销，规范 §6.7 凭证黑名单）"""
        return await JWTUtil.invalidate_token(token)
