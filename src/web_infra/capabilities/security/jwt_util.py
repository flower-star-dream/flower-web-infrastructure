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
              状态存储（JwtTokenStore）与签名密钥/算法（JwtKeyProvider）为 SPI，经 configure 注入；
              未注入时状态存储按框架默认回落（启用 Redis → RedisJwtTokenStore，否则 InMemoryJwtTokenStore），
              key_provider 回落 EnvJwtKeyProvider，向后兼容。
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import timedelta
from typing import Any, ClassVar, Optional

import jwt

from web_infra.infra.constants.auth_constant import AuthConstant
from web_infra.capabilities.db.redis_config import RedisConfig
from web_infra.infra.logging import get_logger
from web_infra.capabilities.security.env_jwt_key_provider import EnvJwtKeyProvider
from web_infra.capabilities.security.in_memory_jwt_token_store import InMemoryJwtTokenStore
from web_infra.capabilities.security.jwt_key_provider_interface import JwtKeyProvider
from web_infra.capabilities.security.jwt_token_store_interface import JwtTokenStore
from web_infra.capabilities.security.redis_jwt_token_store import RedisJwtTokenStore
from web_infra.capabilities.security.secure_config_loader import SecureConfigLoader
from web_infra.capabilities.security.token_verify_status_enum import TokenVerifyStatus
from web_infra.infra.utils.date_util import DateUtil

logger = get_logger("security.jwt")


class JWTUtil:
    """JWT 工具：生成/解析/校验/登出；状态存储与签名密钥/算法走 SPI（启用 Redis 默认 Redis 状态存储，否则内存）"""

    # 凭证即将过期阈值（秒，规范 §6.1 静默刷新）
    REFRESH_THRESHOLD_SECONDS = 300
    # JWT 密钥版本标识（规范 S15-3）
    JWT_KID = "v1"

    _token_store: JwtTokenStore | None = None
    _key_provider: JwtKeyProvider | None = None
    # 框架 Redis 连接配置（Application 装配时经 set_redis_config 注入；启用 Redis 时默认状态存储走 Redis）
    _redis_config: RedisConfig | None = None
    # 类级锁：保护 SPI 注入与懒初始化的 check-then-act（H3 修复：
    # 多线程首次并发调用仅构建一个 store/key_provider，避免状态写入丢失导致随机 401）
    _config_lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def configure(cls, token_store: JwtTokenStore | None = None, key_provider: JwtKeyProvider | None = None) -> None:
        """注入自定义 SPI 实现（进程内全局配置，建议启动期调用一次；优先级最高，覆盖框架自动默认）。

        :param token_store: Token 状态存储（None 回落框架默认：启用 Redis 则 RedisJwtTokenStore，否则 InMemoryJwtTokenStore）
        :param key_provider: 签名密钥/算法（None 回落默认 EnvJwtKeyProvider）
        """
        with cls._config_lock:
            cls._token_store = token_store
            cls._key_provider = key_provider

    @classmethod
    def set_redis(cls, redis: Any) -> None:
        """注入 Redis 客户端，用于 token 状态存储与校验（兼容入口：显式切换为 RedisJwtTokenStore）"""
        with cls._config_lock:
            cls._token_store = RedisJwtTokenStore(redis=redis)

    @classmethod
    def set_redis_config(cls, config: RedisConfig | None) -> None:
        """注入框架 Redis 连接配置（Application 装配调用；启用 Redis 时 JWT Token 状态默认走 Redis）。

        :param config: Redis 连接配置；None 时回落内存实现（清空由默认装配创建的 Redis store，
            显式 configure 注入的自定义 store 不受影响）
        """
        with cls._config_lock:
            cls._redis_config = config
            if config is None and isinstance(cls._token_store, RedisJwtTokenStore):
                cls._token_store = None

    @classmethod
    def _get_token_store(cls) -> JwtTokenStore:
        """获取 Token 状态存储（优先级：configure 自定义 > set_redis 显式 > 框架 Redis 默认 > 内存回落）。

        双重检查锁定：快路径无锁读（GIL 保证单次读原子），未命中才加锁构建，锁内二次确认。
        """
        store = cls._token_store
        if store is not None:
            return store
        with cls._config_lock:
            store = cls._token_store
            if store is not None:
                return store
            if cls._redis_config is not None:
                store = RedisJwtTokenStore(config=cls._redis_config)
            else:
                store = InMemoryJwtTokenStore()
            cls._token_store = store
            return store

    @classmethod
    def _get_key_provider(cls) -> JwtKeyProvider:
        """获取签名密钥/算法提供器（未注入回落默认环境变量实现）；锁内构建保证单实例"""
        provider = cls._key_provider
        if provider is not None:
            return provider
        with cls._config_lock:
            provider = cls._key_provider
            if provider is None:
                provider = EnvJwtKeyProvider()
                cls._key_provider = provider
            return provider

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
        """生成 JWT，并写入 Token 状态存储（同设备凭证复用，规范 §6.2）。

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

        # 同设备凭证复用（规范 §6.2）：store.save 内部完成旧 jti 替换失效
        await cls._get_token_store().save(user_id, jti, ttl_seconds, client_id, device_id)

        key_provider = cls._get_key_provider()
        token = jwt.encode(
            payload,
            key_provider.access_secret(),
            algorithm=key_provider.algorithm(),
            headers={"kid": cls.JWT_KID},
        )
        return token

    @classmethod
    async def verify_token(cls, token: str) -> tuple[Optional[dict[str, Any]], TokenVerifyStatus]:
        """校验 JWT，返回 (payload, 状态)。

        规范 §6.1 静默刷新：签发有效且剩余有效期低于 REFRESH_THRESHOLD_SECONDS 时返回
        TokenVerifyStatus.EXPIRING（而非 VALID）；refresh token（token_type=refresh）禁止作为
        access token 使用，直接判定非法（防混用）。
        """
        key_provider = cls._get_key_provider()
        try:
            payload = jwt.decode(token, key_provider.access_secret(), algorithms=[key_provider.algorithm()])
        except jwt.ExpiredSignatureError:
            return None, TokenVerifyStatus.EXPIRED
        except jwt.InvalidTokenError:
            return None, TokenVerifyStatus.INVALID

        # 防混用（规范 §6.1）：refresh token 与 access token 不同密钥段 + 用途字段双重区分
        if payload.get("token_type") == "refresh":
            return None, TokenVerifyStatus.INVALID

        user_id = payload.get("sub")
        jti = payload.get("jti")
        if not user_id or not jti:
            return None, TokenVerifyStatus.INVALID

        if not await cls._get_token_store().exists(user_id, jti):
            return None, TokenVerifyStatus.REVOKED

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

        - 使用单独密钥段签名 + payload 携带 token_type="refresh"，与 access token 双向防混用；
        - 默认有效期 AuthConstant.AUTH_TOKEN_REFRESH_TTL_DAYS（7 天），可经 expires_days 覆盖；
        - refresh token 不写入 Token 状态存储（登出仅吊销 access token，业务可扩展）。
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

        key_provider = cls._get_key_provider()
        return jwt.encode(
            payload,
            key_provider.refresh_secret(),
            algorithm=key_provider.algorithm(),
            headers={"kid": cls.JWT_KID},
        )

    @classmethod
    async def verify_refresh_token(cls, token: str) -> tuple[Optional[dict[str, Any]], TokenVerifyStatus]:
        """校验 refresh token（规范 §6.1）。

        - 使用单独密钥段解析；payload 的 token_type 必须为 "refresh"，否则视为非法（防与 access token 混用）；
        - 返回 (payload, 状态)：过期返回 EXPIRED，非法/混用返回 INVALID，正常返回 VALID。
        """
        key_provider = cls._get_key_provider()
        try:
            payload = jwt.decode(token, key_provider.refresh_secret(), algorithms=[key_provider.algorithm()])
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
        key_provider = cls._get_key_provider()
        try:
            payload = jwt.decode(token, key_provider.access_secret(), algorithms=[key_provider.algorithm()])
        except jwt.InvalidTokenError:
            return False
        user_id = payload.get("sub")
        jti = payload.get("jti")
        if not user_id or not jti:
            return False
        return await cls._get_token_store().revoke(user_id, jti)

    @classmethod
    async def get_user_id(cls, token: str) -> Optional[str]:
        """从 token 提取用户 ID"""
        payload = await cls.parse_token(token)
        return payload.get("sub") if payload else None

    @classmethod
    async def get_current_device_jti_async(
        cls, user_id: str, client_id: str | None = None, device_id: str | None = None
    ) -> Optional[str]:
        """异步查询同设备当前有效 jti（规范 §6.2 同设备最多 1 个有效凭证并复用）。

        推荐入口（H3 修复）：异步调用方直接 await，无同步桥接的线程创建与事件循环绑定风险；
        Redis 状态存储（注入 loop-bound 客户端）场景必须使用本方法。

        :param user_id: 用户标识
        :param client_id: 客户端标识
        :param device_id: 设备标识
        :return: 当前有效 jti；无记录返回 None
        """
        return await cls._get_token_store().current_jti(user_id, client_id, device_id)

    @classmethod
    def get_current_device_jti(cls, user_id: str, client_id: str | None = None, device_id: str | None = None) -> Optional[str]:
        """查询同设备当前有效 jti（规范 §6.2 同设备最多 1 个有效凭证并复用）。

        兼容入口（历史调用方保持同步签名）：JwtTokenStore.current_jti 为异步 SPI，协程结果
        经事件循环桥接同步取值：无运行中 loop 直接 asyncio.run，已有运行中 loop（异步服务/
        异步测试内同步调用）经独立线程执行并阻塞等待。
        **局限（H3 修复说明）**：桥接线程每次调用新建一个事件循环，仅适用于不绑定事件循环的
        内存实现；Redis 状态存储（注入 loop-bound 客户端）在跨循环场景会抛错，请改用
        get_current_device_jti_async。

        :param user_id: 用户标识
        :param client_id: 客户端标识（不传按 user_id 聚合查询）
        :param device_id: 设备标识
        :return: 当前有效 jti；无记录返回 None
        """
        result = cls._get_token_store().current_jti(user_id, client_id, device_id)
        if not asyncio.iscoroutine(result):
            return result
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(result)
        # 已在运行中的事件循环内：独立线程新建 loop 执行协程，主线程阻塞等待结果
        box: dict[str, Any] = {}

        def _run() -> None:
            box["value"] = asyncio.run(result)

        thread = threading.Thread(target=_run)
        thread.start()
        thread.join()
        return box.get("value")

    # 兼容入口（历史调用方直接引用类方法 _refresh_secret）
    @classmethod
    def _refresh_secret(cls) -> str:
        """refresh token 单独密钥段（规范 §6.1：派生自主密钥，配合 token_type 用途字段与 access token 双向防混用）"""
        return cls._get_key_provider().refresh_secret()
