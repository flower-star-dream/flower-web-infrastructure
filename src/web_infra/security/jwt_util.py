"""
JWT 工具

@Author: 花海
@Date: 2026/08/14 10:00
@Description: JWT Token 生成、解析、校验与登出，遵循规范 §6 认证授权。
              - 凭证即将过期信号（规范 §6.1 静默刷新）：剩余有效期低于 REFRESH_THRESHOLD_SECONDS
                时 verify_token 返回 EXPIRING 而非 VALID，由统一入口拦截触发 refresh token 静默续期；
              - refresh token（§6.1）：单独密钥段 + token_type 用途字段，与 access token 双向防混用；
              - 同设备凭证复用（规范 §6.2）：按 user_id+client_id+device_id 复合键维护最新 jti，
                同设备新签发替换旧 jti（最多 1 个有效凭证）；
              - 密钥版本标识 kid（规范 S15-3：密钥 ≥90 天轮换，kid 标识版本，新旧并行 ≥24h）。
              支持可选 Redis 状态存储（后端主动登出）；密钥从环境变量读取（SecureConfigLoader）。
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Optional

import jwt

from web_infra.constants.auth_constant import AuthConstant
from web_infra.constants.cache_key import CacheKeyBuilder
from web_infra.logging import get_logger
from web_infra.security.secure_config_loader import SecureConfigLoader
from web_infra.security.token_verify_status_enum import TokenVerifyStatus
from web_infra.utils.date_util import DateUtil

logger = get_logger("security.jwt")


class JWTUtil:
    """JWT 工具：生成/解析/校验/登出，可选 Redis 状态存储；支持静默刷新（§6.1）与同设备凭证复用（§6.2）"""

    _redis = None

    # 凭证即将过期阈值（秒，规范 §6.1 静默刷新：剩余有效期低于该值 verify 返回 EXPIRING，触发静默续期）
    REFRESH_THRESHOLD_SECONDS = 300
    # JWT 密钥版本标识（规范 S15-3：kid 标识密钥版本；轮换时更新 kid，旧密钥保留 ≥24h 并行校验）
    JWT_KID = "v1"
    # 同设备凭证复用映射（规范 §6.2）：复合键 (user_id, client_id, device_id) -> 最新 jti。
    # 进程内尽力维护（分布式场景应下沉到 Redis/DB 由业务扩展）；不传 client_id/device_id 时按
    # user_id 聚合（与旧逻辑一致：同用户新签发替换旧 jti）。
    _device_tokens: dict[tuple[str, str, str], str] = {}

    @classmethod
    def set_redis(cls, redis: Any) -> None:
        """注入 Redis 客户端，用于 token 状态存储与校验"""
        cls._redis = redis

    @classmethod
    def _redis_key(cls, user_id: str, jti: str) -> str:
        """token 状态存储 Key（走缓存 Key 模板）"""
        return CacheKeyBuilder.build(CacheKeyBuilder.AUTH_TOKEN, user_id=user_id, jti=jti)

    @classmethod
    def _user_tokens_key(cls, user_id: str) -> str:
        """用户有效 token 集合 Key"""
        return CacheKeyBuilder.build(CacheKeyBuilder.AUTH_USER_TOKENS, user_id=user_id)

    @classmethod
    def _refresh_secret(cls) -> str:
        """refresh token 单独密钥段（规范 §6.1：派生自主密钥，配合 token_type 用途字段与 access token 双向防混用）"""
        return SecureConfigLoader.get_jwt_secret() + ":refresh"

    @classmethod
    def _composite_key(cls, user_id: str, client_id: str | None, device_id: str | None) -> tuple[str, str, str]:
        """构造凭证复用复合键（规范 §6.2：user_id+client_id+device_id；不传时按 user_id 聚合）"""
        return (user_id, client_id or "", device_id or "")

    @classmethod
    async def generate_token(
        cls,
        user_id: str,
        username: str,
        extra_claims: dict | None = None,
        expires_in: int | None = None,
        client_id: str | None = None,
        device_id: str | None = None,
    ) -> str:
        """生成 JWT，并写入 Redis 状态（可选）。

        :param user_id: 用户标识（sub）
        :param username: 用户名
        :param extra_claims: 附加声明（会覆盖默认字段）
        :param expires_in: 有效期（秒）；None 时按 SecureConfigLoader.get_jwt_expire_minutes() 配置
        :param client_id/device_id: 客户端/设备标识（规范 §6.2 同设备凭证复用，不传按 user_id 聚合）
        :return: 签名后的 JWT 字符串
        """
        now = DateUtil.now_utc()
        if expires_in is not None:
            expire = now + timedelta(seconds=expires_in)
            ttl_seconds = int(expires_in)
        else:
            expire_minutes = SecureConfigLoader.get_jwt_expire_minutes()
            expire = now + timedelta(minutes=expire_minutes)
            ttl_seconds = int(expire_minutes * 60)
        jti = str(uuid.uuid4())

        payload = {
            "sub": user_id,
            "username": username,
            "iat": now,
            "exp": expire,
            "iss": AuthConstant.AUTH_JWT_ISSUER,
            "jti": jti,
        }
        if extra_claims:
            payload.update(extra_claims)

        # 同设备凭证复用（规范 §6.2）：新签发前记录旧 jti，签发后更新复合键映射，
        # 使同设备最多 1 个有效凭证（复用语义）
        composite = cls._composite_key(user_id, client_id, device_id)
        old_jti = cls._device_tokens.get(composite)
        cls._device_tokens[composite] = jti

        # kid 标识密钥版本（规范 S15-3），写入 header 供密钥轮换时区分
        token = jwt.encode(
            payload,
            SecureConfigLoader.get_jwt_secret(),
            algorithm=AuthConstant.AUTH_JWT_ALGORITHM,
            headers={"kid": cls.JWT_KID},
        )

        redis = cls._redis
        if redis is not None:
            try:
                if old_jti:
                    # 同设备旧凭证失效（复用语义：新凭证签发后旧凭证不可用）
                    await redis.delete(cls._redis_key(user_id, old_jti))
                    await redis.srem(cls._user_tokens_key(user_id), old_jti)
                await redis.setex(cls._redis_key(user_id, jti), ttl_seconds, "1")
                await redis.sadd(cls._user_tokens_key(user_id), jti)
                await redis.expire(cls._user_tokens_key(user_id), ttl_seconds)
            except Exception as e:
                logger.warning("jwt_redis_store_failed error=%s", str(e))
        return token

    @classmethod
    async def verify_token(cls, token: str) -> tuple[Optional[dict[str, Any]], TokenVerifyStatus]:
        """校验 JWT，返回 (payload, 状态)。

        规范 §6.1 静默刷新：签发有效且剩余有效期低于 REFRESH_THRESHOLD_SECONDS 时返回
        TokenVerifyStatus.EXPIRING（而非 VALID），由统一入口识别后触发 refresh token 静默续期；
        refresh token（token_type=refresh）禁止作为 access token 使用，直接判定非法（防混用）。
        """
        try:
            payload = jwt.decode(token, SecureConfigLoader.get_jwt_secret(), algorithms=[AuthConstant.AUTH_JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            return None, TokenVerifyStatus.EXPIRED
        except jwt.InvalidTokenError:
            return None, TokenVerifyStatus.INVALID

        # 防混用（规范 §6.1）：refresh token 与 access token 使用不同密钥段签发，
        # 此处再校验用途字段，双向拒绝混用
        if payload.get("token_type") == "refresh":
            return None, TokenVerifyStatus.INVALID

        user_id = payload.get("sub")
        jti = payload.get("jti")
        if not user_id or not jti:
            return None, TokenVerifyStatus.INVALID

        redis = cls._redis
        if redis is not None:
            try:
                exists = await redis.get(cls._redis_key(user_id, jti))
                if not exists:
                    return None, TokenVerifyStatus.REVOKED
            except Exception as e:
                logger.warning("jwt_redis_check_failed error=%s", str(e))

        # 即将过期判定（规范 §6.1 静默刷新）：剩余有效期低于阈值返回 EXPIRING
        exp = payload.get("exp")
        if exp is not None:
            remaining = int(exp) - int(DateUtil.utc_now().timestamp())
            if 0 < remaining < cls.REFRESH_THRESHOLD_SECONDS:
                return payload, TokenVerifyStatus.EXPIRING
        return payload, TokenVerifyStatus.VALID

    @classmethod
    async def create_refresh_token(
        cls,
        user_id: str,
        username: str,
        extra_claims: dict | None = None,
        expires_days: int | None = None,
    ) -> str:
        """生成 refresh token（规范 §6.1 静默刷新）。

        - 使用单独密钥段（_refresh_secret）签名 + payload 携带 token_type="refresh"，
          与 access token 双向防混用（verify_token 拒绝 refresh token，verify_refresh_token 拒绝 access token）；
        - 默认有效期 AuthConstant.AUTH_TOKEN_REFRESH_TTL_DAYS（7 天），可经 expires_days 覆盖；
        - refresh token 不写入 Redis 状态存储（登出仅吊销 access token，业务可扩展）。
        """
        now = DateUtil.now_utc()
        days = expires_days if expires_days is not None else AuthConstant.AUTH_TOKEN_REFRESH_TTL_DAYS
        expire = now + timedelta(days=days)
        jti = str(uuid.uuid4())

        payload = {
            "sub": user_id,
            "username": username,
            "iat": now,
            "exp": expire,
            "iss": AuthConstant.AUTH_JWT_ISSUER,
            "jti": jti,
            "token_type": "refresh",
        }
        if extra_claims:
            payload.update(extra_claims)

        return jwt.encode(
            payload,
            cls._refresh_secret(),
            algorithm=AuthConstant.AUTH_JWT_ALGORITHM,
            headers={"kid": cls.JWT_KID},
        )

    @classmethod
    async def verify_refresh_token(cls, token: str) -> tuple[Optional[dict[str, Any]], TokenVerifyStatus]:
        """校验 refresh token（规范 §6.1）。

        - 使用单独密钥段解析；payload 的 token_type 必须为 "refresh"，否则视为非法（防与 access token 混用）；
        - 返回 (payload, TokenVerifyStatus)：过期返回 EXPIRED，非法/混用返回 INVALID，正常返回 VALID。
        """
        try:
            payload = jwt.decode(token, cls._refresh_secret(), algorithms=[AuthConstant.AUTH_JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            return None, TokenVerifyStatus.EXPIRED
        except jwt.InvalidTokenError:
            return None, TokenVerifyStatus.INVALID

        if payload.get("token_type") != "refresh":
            return None, TokenVerifyStatus.INVALID

        user_id = payload.get("sub")
        jti = payload.get("jti")
        if not user_id or not jti:
            return None, TokenVerifyStatus.INVALID
        return payload, TokenVerifyStatus.VALID

    @classmethod
    async def parse_token(cls, token: str) -> Optional[dict[str, Any]]:
        """解析 JWT，失败返回 None"""
        payload, _ = await cls.verify_token(token)
        return payload

    @classmethod
    async def invalidate_token(cls, token: str) -> bool:
        """使指定 token 失效（登出）"""
        try:
            payload = jwt.decode(token, SecureConfigLoader.get_jwt_secret(), algorithms=[AuthConstant.AUTH_JWT_ALGORITHM])
        except jwt.InvalidTokenError:
            return False
        user_id = payload.get("sub")
        jti = payload.get("jti")
        if not user_id or not jti or cls._redis is None:
            return False
        try:
            await cls._redis.delete(cls._redis_key(user_id, jti))
            await cls._redis.srem(cls._user_tokens_key(user_id), jti)
        except Exception as e:
            logger.warning("jwt_redis_invalidate_failed error=%s", str(e))
            return False
        return True

    @classmethod
    async def get_user_id(cls, token: str) -> Optional[str]:
        """从 token 提取用户 ID"""
        payload = await cls.parse_token(token)
        return payload.get("sub") if payload else None

    @classmethod
    def get_current_device_jti(cls, user_id: str, client_id: str | None = None, device_id: str | None = None) -> Optional[str]:
        """查询同设备当前有效 jti（规范 §6.2 同设备最多 1 个有效凭证并复用）。

        供登录/登出/校验场景判断该设备最新凭证；不传 client_id/device_id 时按 user_id 聚合查询。
        """
        return cls._device_tokens.get(cls._composite_key(user_id, client_id, device_id))
