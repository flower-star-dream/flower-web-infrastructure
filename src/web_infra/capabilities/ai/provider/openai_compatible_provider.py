"""
OpenAI 兼容模型供应商

@Author: 花海
@Date: 2026/08/14 23:30
@Description: OpenAI 兼容协议默认实现（AI 规范 §17.4：至少支持 OpenAI 兼容格式作为默认协议）：
              一个实例绑定一个 ModelConfig，provider.name = model_code（模型逻辑名），
              按配置的 api_base/api_key/model_id 调用 /chat/completions 与 /embeddings，
              支持非流式/流式（SSE）；客户端优先复用模型网关连接池注入的流式/非流式客户端
              （AI 规范 §5.1 分池），构造注入与懒创建仅作兜底；
              流式场景施加 TTFT 首包超时与全量生成超时（AI 规范 §4.1）。
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, AsyncIterator

import httpx

from web_infra.capabilities.ai.chat_message import ChatMessage
from web_infra.capabilities.ai.chat_request import ChatRequest
from web_infra.capabilities.ai.chat_response import ChatResponse
from web_infra.capabilities.ai.chat_role_enum import ChatRole
from web_infra.capabilities.ai.chat_stream_chunk import ChatStreamChunk
from web_infra.capabilities.ai.embedding_request import EmbeddingRequest
from web_infra.capabilities.ai.embedding_response import EmbeddingResponse
from web_infra.capabilities.ai.finish_reason_enum import FinishReason
from web_infra.capabilities.ai.model_config import ModelConfig
from web_infra.capabilities.ai.model_provider_interface import ModelProviderInterface
from web_infra.capabilities.ai.usage import Usage
from web_infra.infra.constants import HttpStatusConstant
from web_infra.infra.error.ai_error_code import AiErrorCode


class OpenAICompatibleProvider(ModelProviderInterface):
    """OpenAI 兼容协议模型供应商：按 ModelConfig 自动接入任意兼容端点（AI 规范 §17.4 默认协议）"""

    name: str = "openai_compatible"

    def __init__(self, config: ModelConfig, client: httpx.AsyncClient | None = None) -> None:
        """初始化 OpenAI 兼容供应商。

        :param config: 标准化模型配置（api_base/api_key/model_id/超时等，来自页面化配置或 yml）
        :param client: 外部 httpx 客户端（测试注入 MockTransport 用）；缺省懒创建并自行管理生命周期
        """
        self._config = config
        # 一个实例对应一个模型逻辑名，注册表按 name 路由
        self.name = config.model_code
        self._client: httpx.AsyncClient | None = client
        self._owns_client = client is None
        # 模型网关连接池注入的客户端（流式/非流式分池，AI 规范 §5.1；生命周期由连接池管理）
        self._stream_client: httpx.AsyncClient | None = None
        self._sync_client: httpx.AsyncClient | None = None
        # 懒创建互斥锁（M2 修复：并发首次调用仅创建一个 httpx 客户端，防重复创建泄漏）
        self._client_lock = threading.Lock()

    def attach_clients(
        self,
        stream_client: httpx.AsyncClient | None = None,
        sync_client: httpx.AsyncClient | None = None,
    ) -> None:
        """注入模型网关连接池客户端（AI 规范 §5.1 流式/非流式分池）。

        注入的客户端生命周期由 ConnectionPoolManager 统一管理，供应商不接管（close 不关闭）。

        :param stream_client: 流式调用客户端（连接长时间占用，流式池）
        :param sync_client: 非流式调用客户端（同步池）
        """
        if stream_client is not None:
            self._stream_client = stream_client
        if sync_client is not None:
            self._sync_client = sync_client

    # ------------------------------------------------------------------
    # 对外能力
    # ------------------------------------------------------------------

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """对话生成（非流式）：调用 {api_base}/chat/completions，受全量生成超时约束（AI 规范 §4.1）"""
        payload = self._build_payload(request, stream=False)
        _ttft, total_timeout = self._resolve_timeouts(request)
        try:
            data = await asyncio.wait_for(self._post("/chat/completions", payload), total_timeout)
        except asyncio.TimeoutError as e:
            raise AiErrorCode.THIRD_TIMEOUT.to_exception(message=f"模型调用超时：{self.name}") from e
        return self._parse_chat_response(data)

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatStreamChunk]:
        """流式对话生成：SSE 逐行解析 delta/finish_reason/usage（AI 规范 §9），
        施加 TTFT 首包超时与全量生成超时（AI 规范 §4.1）。
        使用 stream=True 发起请求，避免 httpx 预读整个响应体阻塞流式返回。"""
        payload = self._build_payload(request, stream=True)
        ttft_timeout, total_timeout = self._resolve_timeouts(request)
        client = self._get_client(stream=True)
        raw_request = client.build_request("POST", self._endpoint("/chat/completions"), json=payload)
        try:
            response = await asyncio.wait_for(client.send(raw_request, stream=True), total_timeout)
        except asyncio.TimeoutError as e:
            raise AiErrorCode.THIRD_TIMEOUT.to_exception(message=f"模型流式调用超时：{self.name}") from e
        except httpx.TimeoutException as e:
            raise AiErrorCode.THIRD_TIMEOUT.to_exception(message=f"模型流式调用超时：{self.name}") from e
        self._raise_for_status(response)

        async def _raw() -> AsyncIterator[ChatStreamChunk]:
            """逐行解析 SSE（finally 关闭响应，取消/异常/正常结束均释放连接）"""
            try:
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[len("data: "):].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError as e:
                        raise AiErrorCode.AI_GENERATION_FAILED.to_exception(message="流式响应解析失败") from e
                    choice = (data.get("choices") or [{}])[0]
                    delta = (choice.get("delta") or {}) or {}
                    yield ChatStreamChunk(
                        delta=delta.get("content") or "",
                        finish_reason=self._parse_finish_reason(choice.get("finish_reason")),
                        usage=self._parse_usage(data.get("usage")),
                    )
            finally:
                await response.aclose()

        # TTFT：首包独立超时；后续分片受全量生成超时约束（剩余时间递减）
        iterator = _raw().__aiter__()
        try:
            first = await asyncio.wait_for(iterator.__anext__(), ttft_timeout)
        except asyncio.TimeoutError as e:
            raise AiErrorCode.THIRD_TIMEOUT.to_exception(message=f"模型首 Token 超时（TTFT）：{self.name}") from e
        yield first
        deadline = time.monotonic() + total_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AiErrorCode.THIRD_TIMEOUT.to_exception(message=f"模型全量生成超时：{self.name}")
            try:
                chunk = await asyncio.wait_for(iterator.__anext__(), remaining)
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError as e:
                raise AiErrorCode.THIRD_TIMEOUT.to_exception(message=f"模型全量生成超时：{self.name}") from e
            yield chunk

    async def embedding(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """向量化：调用 {api_base}/embeddings"""
        inputs = [request.input] if isinstance(request.input, str) else request.input
        data = await self._post(
            "/embeddings",
            {"model": self._config.model_id or self._config.model_code, "input": inputs},
        )
        embeddings = [item.get("embedding", []) for item in (data.get("data") or [])]
        return EmbeddingResponse(
            model=data.get("model") or self.name,
            embeddings=embeddings,
            usage=self._parse_usage(data.get("usage")),
        )

    async def close(self) -> None:
        """释放底层 httpx 客户端（应用停机时由模型网关统一调用；外部注入客户端不接管）"""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _build_payload(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        """构建 OpenAI 兼容请求体（可选参数为 None 时不传）"""
        payload: dict[str, Any] = {
            "model": self._config.model_id or self._config.model_code,
            "messages": [self._to_openai_message(m) for m in request.messages],
            "stream": stream,
        }
        temperature = request.temperature if request.temperature is not None else self._config.temperature
        if temperature is not None:
            payload["temperature"] = temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        elif self._config.max_tokens:
            payload["max_tokens"] = self._config.max_tokens
        if self._config.top_p and self._config.top_p > 0:
            payload["top_p"] = self._config.top_p
        if self._config.stop is not None:
            payload["stop"] = self._config.stop
        return payload

    def _to_openai_message(self, message: ChatMessage) -> dict[str, str]:
        """统一消息 -> OpenAI 消息"""
        return {"role": message.role.value, "content": message.content}

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST 请求并解析 JSON（超时/限流/其他错误码映射，AI 规范 §12）"""
        try:
            response = await self._get_client().post(self._endpoint(path), json=payload)
        except httpx.TimeoutException as e:
            raise AiErrorCode.THIRD_TIMEOUT.to_exception(message=f"模型调用超时：{self.name}") from e
        self._raise_for_status(response)
        try:
            return response.json()
        except json.JSONDecodeError as e:
            raise AiErrorCode.AI_GENERATION_FAILED.to_exception(message=f"模型响应解析失败：{self.name}") from e

    def _raise_for_status(self, response: httpx.Response) -> None:
        """HTTP 错误码映射（429 限流、其他第三方不可用）"""
        if response.status_code == HttpStatusConstant.HTTP_OK:
            return
        if response.status_code == HttpStatusConstant.HTTP_TOO_MANY_REQUESTS:
            raise AiErrorCode.THIRD_RATE_LIMITED.to_exception(message=f"模型供应商限流：{self.name}")
        raise AiErrorCode.THIRD_UNAVAILABLE.to_exception(message=f"模型供应商返回 {response.status_code}：{self.name}")

    def _endpoint(self, path: str) -> str:
        """拼接端点（api_base 去尾部斜杠）"""
        return f"{self._config.api_base.rstrip('/')}{path}"

    def _get_client(self, *, stream: bool = False) -> httpx.AsyncClient:
        """获取调用客户端（AI 规范 §5.1 分池优先）。

        优先级：构造注入的客户端（测试 MockTransport/自定义） > 连接池注入的流式/非流式客户端 >
        懒创建兜底（独立使用场景）。

        :param stream: 是否为流式调用（选择流式池客户端）
        """
        if self._client is not None:
            return self._client
        if stream and self._stream_client is not None:
            return self._stream_client
        if not stream and self._sync_client is not None:
            return self._sync_client
        return self._lazy_client()

    def _lazy_client(self) -> httpx.AsyncClient:
        """懒创建 httpx 客户端（超时取自模型配置；仅未注入任何客户端时兜底）。

        双重检查锁定（M2 修复）：并发首次调用仅创建一个客户端，防重复创建泄漏；
        close() 将 _client 置 None 后重新创建亦受锁保护。
        """
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._config.timeout))
                self._owns_client = True
            return self._client

    def _resolve_timeouts(self, request: ChatRequest) -> tuple[float, float]:
        """解析 TTFT 首包超时与全量生成超时（AI 规范 §4.1）。

        请求字段缺省时回退模型配置默认超时（config.timeout）。

        :param request: 统一对话请求
        :return: (ttft_timeout, total_timeout)，单位秒
        """
        default = float(self._config.timeout)
        ttft = request.ttft_timeout_seconds if request.ttft_timeout_seconds is not None else default
        total = request.total_timeout_seconds if request.total_timeout_seconds is not None else default
        return ttft, total

    def _parse_chat_response(self, data: dict[str, Any]) -> ChatResponse:
        """解析 OpenAI 兼容非流式响应 -> 统一响应结构"""
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if not content and message.get("tool_calls"):
            content = json.dumps(message["tool_calls"], ensure_ascii=False)
        return ChatResponse(
            id=data.get("id") or "",
            model=data.get("model") or self.name,
            message=ChatMessage(role=ChatRole.ASSISTANT, content=content),
            finish_reason=self._parse_finish_reason(choice.get("finish_reason")),
            usage=self._parse_usage(data.get("usage")),
        )

    @staticmethod
    def _parse_finish_reason(value: Any) -> FinishReason:
        """OpenAI finish_reason 字符串 -> 统一枚举（未知值按 stop）"""
        try:
            return FinishReason(value) if value else FinishReason.STOP
        except ValueError:
            return FinishReason.STOP

    @staticmethod
    def _parse_usage(data: Any) -> Usage:
        """OpenAI usage 结构 -> 统一用量结构（缺省为 0）"""
        if not isinstance(data, dict):
            return Usage()
        return Usage(
            prompt_tokens=int(data.get("prompt_tokens") or 0),
            completion_tokens=int(data.get("completion_tokens") or 0),
            total_tokens=int(data.get("total_tokens") or 0),
        )
