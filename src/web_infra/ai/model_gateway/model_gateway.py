"""
统一模型网关

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 统一模型网关（AI 规范 §2.2/§2.3/§4/§5 收敛）：
              场景路由 → 连接池客户端注入 → 内容审核 → 主备降级 → 可重试退避重试 →
              并发控制 → 配额 → 计费 → 指标 → 日志；
              业务只依赖统一出入参结构，未配置供应商快速失败 E4-AI-001。
              AI-2/3/5/8 整改：三入口统一配额检查（user/scene 维度参与）、用量聚合字段透传、
              流内错误分片终止、模型访问权限校验（AllowAll 默认放行）。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any, AsyncIterator

from web_infra.ai.chat_message import ChatMessage
from web_infra.ai.chat_request import ChatRequest
from web_infra.ai.chat_response import ChatResponse
from web_infra.ai.chat_role_enum import ChatRole
from web_infra.ai.chat_stream_chunk import ChatStreamChunk
from web_infra.ai.content_guard_interface import ContentGuardInterface
from web_infra.ai.embedding_request import EmbeddingRequest
from web_infra.ai.embedding_response import EmbeddingResponse
from web_infra.ai.finish_reason_enum import FinishReason
from web_infra.ai.model_access_policy import AllowAllModelAccessPolicy, ModelAccessPolicy
from web_infra.ai.model_gateway.model_router import ModelRouter
from web_infra.ai.model_provider_interface import ModelProviderInterface
from web_infra.ai.model_provider_registry import ModelProviderRegistry
from web_infra.ai.quota.quota_manager import QuotaManager
from web_infra.ai.concurrency.concurrency_guard import ConcurrencyGuard
from web_infra.ai.connection_pool.connection_pool import ConnectionPoolManager
from web_infra.ai.usage import Usage
from web_infra.ai.usage_accounting import UsageAccounting
from web_infra.constants import INFRA_CALL_CONNECT_TIMEOUT_SECONDS, INFRA_CALL_MAX_RETRIES
from web_infra.context.request_context import RequestContext
from web_infra.error.ai_error_code import AiErrorCode
from web_infra.error.web_infra_exception import WebInfraException
from web_infra.monitoring.ai_metrics import (
    record_ai_call,
    record_ai_cost,
    record_ai_duration,
    record_ai_tokens,
    record_ai_ttft,
)

if TYPE_CHECKING:
    from web_infra.ai.ai_cache import AICache


class ModelGateway:
    """统一模型网关：路由/降级/重试/并发/配额/计费/指标/内容审核收敛"""

    def __init__(
        self,
        router: ModelRouter,
        *,
        registry: ModelProviderRegistry | None = None,
        pool_manager: ConnectionPoolManager | None = None,
        quota_manager: QuotaManager | None = None,
        usage_accounting: UsageAccounting | None = None,
        content_guard: ContentGuardInterface | None = None,
        access_policy: ModelAccessPolicy | None = None,
        ai_cache: AICache | None = None,
        default_concurrency: int = 8,
        max_retries: int = INFRA_CALL_MAX_RETRIES,
        retry_backoff_base_seconds: float = INFRA_CALL_CONNECT_TIMEOUT_SECONDS,
    ) -> None:
        """初始化模型网关。

        :param router: 场景路由（必选）
        :param registry: 供应商注册表（默认 ModelProviderRegistry）
        :param pool_manager: 连接池管理（可选，流式/非流式分池客户端注入供应商复用）
        :param quota_manager: 配额管理（可选，配置后 chat/stream_chat/embed 三入口按
              tenant/user/scene 维度限调用次数；AI-2 整改）
        :param usage_accounting: 用量计费（可选；AI-3：记录用量时透传 tenant/scene/provider 聚合维度）
        :param content_guard: 内容安全审核（可选，默认不启用；启用后输入输出均审核，BLOCK 抛 E4-AI-002）
        :param access_policy: 模型访问权限策略（可选，AI-8；默认 AllowAllModelAccessPolicy 放行，
              业务注入基于 RBAC 的策略后按模型/租户/用户/场景校验，无权限抛 E2-PERM-*）
        :param ai_cache: AI 结果缓存（可选，AI-4 整改；注入后非流式确定性 chat 先查缓存，
              命中直接返回并埋点 cache_hit，未命中调用模型后写入缓存并埋点 cache_miss；
              stream_chat / embed 不缓存，避免过度设计）
        :param default_concurrency: 单供应商默认并发上限
        :param max_retries: retryable 错误最大重试次数（默认对齐规范 §7.2 INFRA_CALL_MAX_RETRIES=2）
        :param retry_backoff_base_seconds: 指数退避基数秒（默认对齐规范 §7.1 连接超时 1s）
        """
        self._router = router
        self._registry = registry or ModelProviderRegistry
        self._pool_manager = pool_manager
        self._quota_manager = quota_manager
        self._usage_accounting = usage_accounting
        self._content_guard = content_guard
        self._access_policy = access_policy or AllowAllModelAccessPolicy()
        self._ai_cache = ai_cache
        self._guards: dict[str, ConcurrencyGuard] = {}
        self._default_concurrency = default_concurrency
        self._max_retries = max_retries
        self._retry_backoff_base_seconds = retry_backoff_base_seconds
        # 已注入连接池客户端的模型（避免重复注入）
        self._injected: set[str] = set()

    # ------------------------------------------------------------------
    # 对外能力
    # ------------------------------------------------------------------

    async def chat(self, request: ChatRequest, *, scene: str = "", tenant_id: str = "", user_id: str = "") -> ChatResponse:
        """对话生成（非流式）：路由 → 权限校验（AI-8） → 配额检查（AI-2） → 内容审核（输入） →
        并发 → 主备降级 → retryable 指数退避重试 → 内容审核（输出） → 计费/指标/用量配额累计。

        :param request: 统一对话请求
        :param scene: 调用场景（路由依据；AI-2 配额 scene 维度参与）
        :param tenant_id: 租户标识（配额/权限维度）
        :param user_id: 用户标识（AI-2 配额 user 维度、AI-8 权限维度；缺省回退请求上下文）
        :return: 统一对话响应
        :raises BizException: 权限校验失败抛 E2-PERM-*；配额超限抛 E1-RATE-000/E4-AI-005；
              内容审核拒绝抛 E4-AI-002；全部候选模型失败抛 E3-THIRD-001
        """
        entry = self._router.route(scene)
        self._check_access(entry.primary, tenant_id, user_id, scene)
        await self._check_quota(tenant_id, user_id, scene)
        self._check_input(request)
        # AI-4：注入 AICache 时非流式确定性场景缓存优先——命中直接返回（埋点 cache_hit），
        # 未命中走模型调用并在成功（主模型）后写入缓存（埋点 cache_miss）。
        # 缓存内容写入前已通过输出审核，命中直接返回不重复审核；输入审核已在上方执行，缓存命中不漏审。
        cached = await self._try_cache_hit(request, entry, tenant_id, user_id)
        if cached is not None:
            return cached
        candidates = self._candidates(entry)
        effective_request = self._ensure_idempotency_key(request)

        last_error: Exception | None = None
        for model_name in candidates:
            # AI-8：备用模型切换时同样按模型/租户/用户/场景校验权限（主模型已在入口校验）
            if model_name != entry.primary:
                self._check_access(model_name, tenant_id, user_id, scene)
            provider = self._registry.get(model_name)
            await self._attach_pool_clients(provider, model_name)
            start = time.monotonic()
            for attempt in range(self._max_retries + 1):
                try:
                    async with self._get_guard(model_name):
                        response = await provider.chat(effective_request)
                except Exception as e:
                    last_error = e
                    record_ai_call(model_name, "error")
                    if self._is_content_rejected(e):
                        raise  # 内容审核拒绝：直接抛给调用方，不重试不降级
                    if self._is_retryable_error(e) and attempt < self._max_retries:
                        await asyncio.sleep(self._backoff_delay(attempt))
                        continue
                    break  # 非可重试或已达最大重试：降级下一候选
                # 输出内容审核（BLOCK 直接抛，不重试不降级）
                self._check_output(response)
                # AI-3：计费打点透传 tenant_id/scene/provider 聚合维度
                self._record_success(
                    model_name, entry, response, start,
                    provider=provider.name, tenant_id=tenant_id, scene=scene,
                )
                # AI-2：按实际用量累计 Token 配额（不重复计调用次数，超限由后续入口检查拦截）
                await self._consume_usage(tenant_id, user_id, scene, response.usage)
                # AI-4：仅主模型成功响应写缓存（降级响应不落缓存，避免主模型恢复后命中降级内容）
                if self._ai_cache is not None and model_name == entry.primary:
                    await self._write_cache(request, response, entry, tenant_id, user_id)
                return response
        # 主备全部失败：降级计数已由 _record_success 缺失体现，统一抛第三方不可用
        if last_error is not None:
            raise AiErrorCode.THIRD_UNAVAILABLE.to_exception(message=f"模型调用失败：{last_error}")
        raise AiErrorCode.AI_NOT_CONFIGURED.to_exception(message="无可用模型")

    async def stream_chat(
        self,
        request: ChatRequest,
        *,
        scene: str = "",
        tenant_id: str = "",
        user_id: str = "",
    ) -> AsyncIterator[ChatStreamChunk]:
        """流式对话生成：TTFT 计时 + 权限校验（AI-8） + 配额检查（AI-2） + 内容审核（输入/输出）
        + 未产出前允许降级与重试（AI 规范 §4.2）+ 已产出后流内错误分片终止（AI-5）。

        流开始（产出首个分片）前 retryable 异常可指数退避重试，仍失败可降级到备用；
        已产出分片后异常走统一流内错误分片终止（error 携带错误码、finish_reason=ERROR），
        不再整体重试/降级——调用方消费到 error 分片即知流中断原因；
        未产出分片前仍抛异常（保持异常传播语义）。每个分片返回前做输出审核，BLOCK 抛 E4-AI-002。

        :param request: 统一对话请求
        :param scene: 调用场景（路由依据；AI-2 配额 scene 维度参与）
        :param tenant_id: 租户标识（AI-2 配额维度、AI-8 权限维度）
        :param user_id: 用户标识（AI-2 配额 user 维度、AI-8 权限维度）
        :raises BizException: 权限校验失败抛 E2-PERM-*；配额超限抛 E1-RATE-000/E4-AI-005；
              未产出分片前的内容审核拒绝/供应商失败仍抛异常
        """
        entry = self._router.route(scene)
        self._check_access(entry.primary, tenant_id, user_id, scene)
        await self._check_quota(tenant_id, user_id, scene)
        self._check_input(request)
        candidates = self._candidates(entry)
        effective_request = self._ensure_idempotency_key(request)
        last_error: Exception | None = None
        started = False
        for model_name in candidates:
            # AI-8：备用模型切换时同样校验权限（主模型已在入口校验）
            if model_name != entry.primary:
                self._check_access(model_name, tenant_id, user_id, scene)
            provider = self._registry.get(model_name)
            await self._attach_pool_clients(provider, model_name)
            start = time.monotonic()
            ttft_recorded = False
            for attempt in range(self._max_retries + 1):
                output_buffer = ""
                try:
                    async with self._get_guard(model_name):
                        async for chunk in provider.stream_chat(effective_request):
                            if not ttft_recorded:
                                record_ai_ttft(model_name, time.monotonic() - start)
                                ttft_recorded = True
                            # 输出审核：分片返回前累计检查，BLOCK 立即中断
                            if self._content_guard is not None:
                                output_buffer += chunk.delta
                                result = self._content_guard.check_output(output_buffer)
                                if result.blocked:
                                    raise AiErrorCode.AI_CONTENT_REJECTED.to_exception(message=result.message)
                            started = True
                            yield chunk
                            if chunk.finish_reason is not None and chunk.usage is not None:
                                record_ai_duration(model_name, time.monotonic() - start)
                                record_ai_tokens(model_name, chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
                                # AI-3：计费打点透传 tenant_id/scene/provider 聚合维度
                                self._record_cost(
                                    model_name,
                                    chunk.usage.prompt_tokens,
                                    chunk.usage.completion_tokens,
                                    provider=provider.name,
                                    tenant_id=tenant_id,
                                    scene=scene,
                                )
                                # AI-2：按实际用量累计 Token 配额（不重复计调用次数，超限由后续入口检查拦截）
                                await self._consume_usage(tenant_id, user_id, scene, chunk.usage)
                    record_ai_call(model_name, "success")
                    return
                except Exception as e:
                    last_error = e
                    record_ai_call(model_name, "error")
                    if self._is_content_rejected(e):
                        raise  # 内容审核拒绝：直接抛给调用方
                    if started:
                        # AI-5：已产出分片后异常 → 统一流内错误分片终止（error 携带错误码，finish_reason=ERROR），
                        # 不再整体重试/降级；调用方消费到 error 分片即知流中断原因，而非异常中断
                        yield ChatStreamChunk(error=self._error_code_of(e), finish_reason=FinishReason.ERROR)
                        return
                    if self._is_retryable_error(e) and attempt < self._max_retries:
                        await asyncio.sleep(self._backoff_delay(attempt))
                        continue
                    break  # 非可重试或已达最大重试：降级到备用
        if last_error is not None:
            raise AiErrorCode.THIRD_UNAVAILABLE.to_exception(message=f"模型流式调用失败：{last_error}")

    async def embed(
        self,
        request: EmbeddingRequest,
        *,
        scene: str = "",
        tenant_id: str = "",
        user_id: str = "",
    ) -> EmbeddingResponse:
        """向量化调用（走场景路由，无降级链；AI-2：入口统一配额检查，AI-8：权限校验）"""
        entry = self._router.route(scene)
        self._check_access(entry.primary, tenant_id, user_id, scene)
        await self._check_quota(tenant_id, user_id, scene)
        provider = self._registry.get(entry.primary)
        await self._attach_pool_clients(provider, entry.primary)
        async with self._get_guard(entry.primary):
            return await provider.embedding(request)

    async def close(self) -> None:
        """释放连接池（应用停机时调用）"""
        if self._pool_manager is not None:
            await self._pool_manager.close()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _candidates(self, entry: Any) -> list[str]:
        """候选模型列表：主模型 + 备用模型"""
        return [entry.primary] + list(entry.backups)

    # ------------------------------------------------------------------
    # AI-4：结果缓存（AICache 注入时启用；stream_chat / embed 不缓存，避免过度设计）
    # ------------------------------------------------------------------

    async def _try_cache_hit(
        self,
        request: ChatRequest,
        entry: Any,
        tenant_id: str,
        user_id: str,
    ) -> ChatResponse | None:
        """缓存优先读取（AI-4）：命中返回缓存响应并埋点 cache_hit，未命中埋点 cache_miss。

        仅注入 AICache 时生效；Key 复用 AICache 现有逻辑（prompt/model_code/model_version/
        tenant_id/params + user_id 用户维度，见 ai_cache._build_key）。

        :param request: 统一对话请求
        :param entry: 路由结果（主模型编码作为缓存 model_code）
        :param tenant_id: 租户标识（缓存租户隔离）
        :param user_id: 用户标识（缺省回退请求上下文 RequestContext.get_user_id()）
        :return: 命中时按缓存内容构造的统一响应；未命中返回 None
        """
        if self._ai_cache is None:
            return None
        cached = await self._ai_cache.get(
            prompt=self._cache_prompt(request),
            model_code=entry.primary,
            model_version=request.model_version or "",
            tenant_id=tenant_id,
            user_id=user_id or RequestContext.get_user_id(),
            params=self._cache_params(request),
        )
        if cached is None:
            record_ai_call(entry.primary, "cache_miss")
            return None
        record_ai_call(entry.primary, "cache_hit")
        return ChatResponse(
            model=entry.primary,
            message=ChatMessage(role=ChatRole.ASSISTANT, content=cached),
        )

    async def _write_cache(self, request: ChatRequest, response: ChatResponse, entry: Any, tenant_id: str, user_id: str) -> None:
        """缓存写入（AI-4）：模型成功响应落缓存，Key 与读取完全一致（同 _try_cache_hit）。

        :param request: 统一对话请求（缓存 Key 材料）
        :param response: 模型成功响应（已通过输出审核）
        :param entry: 路由结果（主模型编码作为缓存 model_code）
        :param tenant_id: 租户标识
        :param user_id: 用户标识
        """
        if self._ai_cache is None:
            return
        await self._ai_cache.set(
            prompt=self._cache_prompt(request),
            response=response.message.content,
            model_code=entry.primary,
            model_version=request.model_version or "",
            tenant_id=tenant_id,
            user_id=user_id or RequestContext.get_user_id(),
            params=self._cache_params(request),
        )

    def _cache_prompt(self, request: ChatRequest) -> str:
        """缓存 Key 的 prompt 材料：消息内容拼接（与内容审核文本口径一致）"""
        return "\n".join(message.content for message in request.messages)

    def _cache_params(self, request: ChatRequest) -> dict[str, Any]:
        """缓存 Key 的关键参数（影响结果确定性的参数，与 ai_cache 参数维度对齐）"""
        params: dict[str, Any] = {}
        if request.temperature is not None:
            params["temperature"] = request.temperature
        if request.max_tokens is not None:
            params["max_tokens"] = request.max_tokens
        return params

    async def _attach_pool_clients(self, provider: ModelProviderInterface, model_name: str) -> None:
        """将连接池流式/非流式客户端注入供应商（AI 规范 §5.1 分池生效；仅首次注入）。

        无连接池或供应商未实现 attach_clients（自定义供应商）时静默跳过。

        :param provider: 供应商实例
        :param model_name: 模型逻辑名（注入去重键）
        """
        if self._pool_manager is None or model_name in self._injected:
            return
        attach = getattr(provider, "attach_clients", None)
        if not callable(attach):
            return
        stream_client = await self._pool_manager.get_stream_client()
        sync_client = await self._pool_manager.get_sync_client()
        attach(stream_client=stream_client, sync_client=sync_client)
        self._injected.add(model_name)

    def _ensure_idempotency_key(self, request: ChatRequest) -> ChatRequest:
        """幂等键兜底：请求未携带时自动生成一次并透传，重试复用同一键（AI 规范 §4.2）。

        :param request: 原始请求
        :return: 带幂等键的请求（已携带时原样返回，未携带时生成副本）
        """
        if request.idempotency_key:
            return request
        return request.model_copy(update={"idempotency_key": uuid.uuid4().hex})

    def _is_retryable_error(self, error: Exception) -> bool:
        """是否可重试错误（仅 E3-THIRD-* 等标记 retryable 的错误码，AI 规范 §4.2）"""
        return isinstance(error, WebInfraException) and bool(error.error_code.retryable)

    def _is_content_rejected(self, error: Exception) -> bool:
        """是否为内容审核拒绝错误（直接抛给调用方，不重试不降级）"""
        return (
            isinstance(error, WebInfraException)
            and error.error_code.code == AiErrorCode.AI_CONTENT_REJECTED.code
        )

    def _backoff_delay(self, attempt: int) -> float:
        """指数退避延时：base * 2^attempt（AI 规范 §7.2）"""
        return self._retry_backoff_base_seconds * (2 ** attempt)

    def _check_input(self, request: ChatRequest) -> None:
        """输入内容审核：BLOCK 抛 E4-AI-002（AI 规范 §7.2）"""
        if self._content_guard is None:
            return
        text = "\n".join(message.content for message in request.messages)
        result = self._content_guard.check_input(text)
        if result.blocked:
            raise AiErrorCode.AI_CONTENT_REJECTED.to_exception(message=result.message)

    def _check_output(self, response: ChatResponse) -> None:
        """输出内容审核：BLOCK 抛 E4-AI-002（AI 规范 §7.2）"""
        if self._content_guard is None:
            return
        result = self._content_guard.check_output(response.message.content)
        if result.blocked:
            raise AiErrorCode.AI_CONTENT_REJECTED.to_exception(message=result.message)

    def _get_guard(self, model_name: str) -> ConcurrencyGuard:
        """获取单供应商并发控制器（按模型懒创建）"""
        guard = self._guards.get(model_name)
        if guard is None:
            guard = ConcurrencyGuard(max_concurrency=self._default_concurrency)
            self._guards[model_name] = guard
        return guard

    async def _check_quota(self, tenant_id: str, user_id: str, scene: str = "") -> None:
        """模型网关级配额检查（AI-2：按用户/租户/接口限流，配额覆盖 chat/stream/embed，user/scene 维度参与）。

        租户维度必查（缺省 no-tenant 占位，保持现状兼容）；user/scene 维度仅在有值时参与，
        避免匿名调用/未命名场景被误伤。超限由 QuotaManager 抛 E1-RATE-000（调用/Token）
        或 E4-AI-005（成本预算耗尽）。

        :param tenant_id: 租户标识
        :param user_id: 用户标识（AI-2 user 维度参与；空值跳过）
        :param scene: 调用场景（AI-2 scene 维度参与；空值跳过）
        """
        if self._quota_manager is None:
            return
        # 租户维度（兼容现状：tenant 必查，缺省 no-tenant 占位）
        await self._quota_manager.check_and_consume("tenant", tenant_id or "no-tenant")
        # 用户维度（AI-2：user 维度参与限流；未传用户标识时跳过，避免误伤匿名调用）
        if user_id:
            await self._quota_manager.check_and_consume("user", user_id)
        # 场景维度（AI-2：scene 维度参与限流；未传场景时跳过）
        if scene:
            await self._quota_manager.check_and_consume("scene", scene)

    async def _consume_usage(self, tenant_id: str, user_id: str, scene: str, usage: Usage) -> None:
        """按实际 Token 用量累计配额（AI-2：Token/成本配额覆盖 chat/stream/embed）。

        模型调用成功后调用，仅累计不增加调用次数；本次调用已完成、超限不抛错
        （由下一次入口 _check_quota 基于累计值拦截），避免流式结束分片后抛错中断流。

        :param tenant_id: 租户标识
        :param user_id: 用户标识（空值跳过）
        :param scene: 调用场景（空值跳过）
        :param usage: 实际 Token 用量
        """
        if self._quota_manager is None:
            return
        tokens = (usage.prompt_tokens or 0) + (usage.completion_tokens or 0)
        if tokens <= 0:
            return
        await self._quota_manager.consume_usage("tenant", tenant_id or "no-tenant", tokens=tokens)
        if user_id:
            await self._quota_manager.consume_usage("user", user_id, tokens=tokens)
        if scene:
            await self._quota_manager.consume_usage("scene", scene, tokens=tokens)

    def _check_access(self, model_name: str, tenant_id: str, user_id: str, scene: str) -> None:
        """模型/能力使用权限校验（AI-8）：无权限抛 E2-PERM-*；默认 AllowAll 放行。

        :param model_name: 模型逻辑名
        :param tenant_id: 租户标识
        :param user_id: 用户标识
        :param scene: 调用场景
        """
        self._access_policy.require_access(model_name, tenant_id, user_id, scene or None)

    def _error_code_of(self, error: Exception) -> str:
        """提取错误码：WebInfraException 用其错误码，其他异常统一 E4-AI-004（AI 规范 §12）"""
        if isinstance(error, WebInfraException):
            return error.error_code.code
        return AiErrorCode.AI_GENERATION_FAILED.code

    def _record_success(
        self,
        model_name: str,
        entry: Any,
        response: ChatResponse,
        start: float,
        *,
        provider: str = "",
        tenant_id: str = "",
        scene: str = "",
    ) -> None:
        """成功调用后的指标与计费打点（AI-3：计费透传 provider/tenant_id/scene 聚合维度）"""
        duration = time.monotonic() - start
        outcome = "degraded" if model_name != entry.primary else "success"
        record_ai_call(model_name, outcome)
        record_ai_duration(model_name, duration)
        usage = response.usage
        if usage is not None:
            record_ai_tokens(model_name, usage.prompt_tokens, usage.completion_tokens)
            self._record_cost(
                model_name,
                usage.prompt_tokens,
                usage.completion_tokens,
                provider=provider,
                tenant_id=tenant_id,
                scene=scene,
            )

    def _record_cost(
        self,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        provider: str = "",
        tenant_id: str = "",
        scene: str = "",
    ) -> None:
        """成本记录（模型网关不持有单价时成本为 0，由业务侧按模型配置核算；AI-3 透传聚合维度）"""
        if self._usage_accounting is None:
            return
        record = self._usage_accounting.record(
            Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
            model_name,
            provider=provider,
            tenant_id=tenant_id,
            scene=scene,
        )
        if record.cost > 0:
            record_ai_cost(model_name, record.cost)
