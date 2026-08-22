"""
三方登录编排服务

@Author: 花海
@Date: 2026/08/16 14:00
@Description: 三方登录统一编排（规范 §6.8 认证域）：生成授权跳转 URL、回调登录（换 token →
              拉 userinfo → 查绑定 → 签发框架自有 JWT）、已登录用户绑定/解绑。
              登录成功复用 JWTUtil 签发自有 JWT，后续鉴权走 AuthMiddleware，业务禁止自行解析凭证。
"""
from __future__ import annotations

from datetime import datetime, timezone

from web_infra.infra.error import BizException, CommonErrorCode
from web_infra.capabilities.event import (
    AuthLoginFailedEvent,
    AuthLoginSuccessEvent,
    publish_event,
)
from web_infra.capabilities.security.jwt_util import JWTUtil
from web_infra.capabilities.security.social.social_binding_store import SocialBinding, SocialBindingStore
from web_infra.capabilities.security.social.social_login_result import SocialLoginResult
from web_infra.capabilities.security.social.social_platform_interface import SocialPlatform
from web_infra.capabilities.security.social.social_platform_registry import SocialPlatformRegistry
from web_infra.capabilities.security.social.social_user_info import SocialUserInfo


class SocialLoginService:
    """三方登录编排：跳转 URL / 登录 / 绑定 / 解绑，登录成功签发框架自有 JWT"""

    def __init__(self, registry: SocialPlatformRegistry, binding_store: SocialBindingStore) -> None:
        self._registry = registry
        self._binding_store = binding_store

    def _require_platform(self, provider: str) -> SocialPlatform:
        """获取平台；未注册抛 E2-AUTH-005"""
        platform = self._registry.get(provider)
        if platform is None:
            raise CommonErrorCode.AUTH_SOCIAL_PLATFORM_NOT_CONFIGURED.to_exception(message=f"三方平台未注册: {provider}")
        return platform

    async def generate_authorize_url(self, provider: str, redirect_uri: str, state: str) -> str:
        """生成授权跳转 URL（state 由业务生成，防 CSRF）"""
        return await self._require_platform(provider).build_authorize_url(state, redirect_uri)

    async def login(self, provider: str, code: str, redirect_uri: str,
                    require_bound: bool = False) -> SocialLoginResult:
        """三方登录：换 token → 拉 userinfo → 查绑定。

        已绑定：签发框架自有 JWT，返回 bound=True；
        未绑定：require_bound=False（默认）返回 bound=False 待绑定信号，由业务决定自动注册或引导绑定；
                require_bound=True 时抛 E2-AUTH-007。
        """
        try:
            platform = self._require_platform(provider)
            token = await platform.exchange_token(code, redirect_uri)
            user_info = await platform.fetch_userinfo(token)
            binding = await self._binding_store.find_by_platform(provider, user_info.openid)
            if binding is not None:
                access_token = await JWTUtil.generate_token(
                    user_id=binding.user_id,
                    username=user_info.nickname or user_info.openid,
                    extra_claims={"login_type": "social"},
                )
                # 绑定成功并签发自有 JWT：发布登录成功事件（无 app 引用，经模块级总线持有器）
                await publish_event(
                    AuthLoginSuccessEvent(
                        payload={
                            "provider": provider,
                            "user_id": binding.user_id,
                            "openid": user_info.openid,
                        }
                    )
                )
                return SocialLoginResult(access_token=access_token, user_id=binding.user_id, user_info=user_info, bound=True)
            if require_bound:
                raise CommonErrorCode.AUTH_SOCIAL_NOT_BOUND.to_exception(message=f"三方账号未绑定: {provider}/{user_info.openid}")
            return SocialLoginResult(access_token=None, user_id=None, user_info=user_info, bound=False)
        except Exception as exc:  # noqa: BLE001 - 登录整体失败统一次处理并保留原异常语义
            # 登录整体失败：发布登录失败事件，再原样抛出（keep 原错误码/语义不变）
            await publish_event(AuthLoginFailedEvent(payload={"provider": provider, "reason": str(exc)}))
            raise

    async def bind(self, provider: str, code: str, redirect_uri: str, user_id: str) -> SocialBinding:
        """已登录用户绑定三方账号：拉取 userinfo → 已被其他用户绑定抛 E2-AUTH-008 → 落库（同用户幂等）。

        并发容错（M3 修复）：绑定前检查与落库间的竞态窗口内另一请求可能已先行绑定，
        捕获 COMMON_CONFLICT 后重查，属主为当前用户则幂等返回既有绑定。
        """
        platform = self._require_platform(provider)
        token = await platform.exchange_token(code, redirect_uri)
        user_info = await platform.fetch_userinfo(token)
        existing = await self._binding_store.find_by_platform(provider, user_info.openid)
        if existing is not None:
            if existing.user_id != user_id:
                raise CommonErrorCode.AUTH_SOCIAL_ALREADY_BOUND.to_exception(
                    message=f"三方账号已被其他用户绑定: {provider}/{user_info.openid}"
                )
            return existing  # 同用户重复绑定幂等返回
        binding = SocialBinding(
            provider=provider,
            openid=user_info.openid,
            user_id=user_id,
            bound_at=datetime.now(timezone.utc),
        )
        try:
            await self._binding_store.bind(binding)
        except BizException as exc:
            if exc.code != CommonErrorCode.COMMON_CONFLICT.code:
                raise
            # 并发竞态：另一请求已先行绑定（M3 修复），属主为当前用户则幂等返回
            raced = await self._binding_store.find_by_platform(provider, user_info.openid)
            if raced is not None and raced.user_id == user_id:
                return raced
            raise CommonErrorCode.AUTH_SOCIAL_ALREADY_BOUND.to_exception(
                message=f"三方账号已被其他用户绑定: {provider}/{user_info.openid}"
            )
        return binding

    async def unbind(self, provider: str, openid: str, user_id: str) -> bool:
        """解绑：校验绑定属主（非属主抛 PERM_DENIED）"""
        binding = await self._binding_store.find_by_platform(provider, openid)
        if binding is None:
            return False
        if binding.user_id != user_id:
            raise CommonErrorCode.PERM_DENIED.to_exception(message="无权解绑他人三方账号")
        return await self._binding_store.unbind(provider, openid)
