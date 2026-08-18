"""
模型自动注册与 OpenAI 兼容供应商测试

@Author: 花海
@Date: 2026/08/14 23:40
@Description: 验证（AI 规范 §17.4 页面化模型配置）：
              1) OpenAI 兼容默认协议 chat/stream_chat/embedding 与错误码映射；
              2) ModelProviderFactory 自定义供应商 SPI 接入；
              3) ModelAutoRegistrar 按配置清单/配置来源自动同步 SPI 注册表；
              4) application 装配闭环：yml models -> 自动注册 -> 模型网关可用。
"""
import httpx
import pytest
from typing import Any

from web_infra.capabilities.ai import (
    ChatMessage,
    ChatRequest,
    ChatRole,
    EmbeddingRequest,
    ModelAutoRegistrar,
    ModelConfig,
    ModelGateway,
    ModelProviderFactory,
    ModelProviderRegistry,
    OpenAICompatibleProvider,
)
from web_infra.core.application import create_app
from web_infra.capabilities.ai.dict_model_config_store import DictModelConfigStore
from web_infra.infra.error import BizException

API_BASE = "http://mock.test/v1"


def _config(**overrides: Any) -> ModelConfig:
    """构造最小模型配置（model_id 缺省回落 model_code）"""
    base: dict[str, Any] = dict(
        id=1,
        model_name="Mock Chat",
        model_code="mock-chat",
        provider="openai_compatible",
        api_base=API_BASE,
        api_key="sk-test",
    )
    base.update(overrides)
    return ModelConfig(**base)


def _json_handler(payload: dict) -> httpx.MockTransport:
    """按固定响应体构造 MockTransport"""
    return httpx.MockTransport(lambda request: httpx.Response(200, json=payload))


def _provider(payload: dict, config: ModelConfig | None = None) -> OpenAICompatibleProvider:
    """构造绑定 MockTransport 的 OpenAI 兼容供应商"""
    return OpenAICompatibleProvider(
        config or _config(),
        client=httpx.AsyncClient(transport=_json_handler(payload)),
    )


@pytest.fixture
def clean_registry():
    """测试后清理全局供应商注册表，避免污染其他用例"""
    before = dict(ModelProviderRegistry._providers)
    yield
    ModelProviderRegistry._providers.clear()
    ModelProviderRegistry._providers.update(before)


@pytest.fixture
def clean_factory():
    """测试后清理供应商工厂注册表"""
    before = dict(ModelProviderFactory._factories)
    yield
    ModelProviderFactory._factories.clear()
    ModelProviderFactory._factories.update(before)


# ------------------------------------------------------------------
# OpenAI 兼容默认协议
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_chat_maps_response():
    """非流式响应映射为统一结构（model_id 透传厂商真实模型 ID）"""
    provider = _provider(
        {
            "id": "chatcmpl-1",
            "model": "mock-chat-id",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        },
        _config(model_id="mock-chat-id"),
    )
    response = await provider.chat(
        ChatRequest(model="mock-chat", messages=[ChatMessage(role=ChatRole.USER, content="hello")])
    )
    assert response.model == "mock-chat-id"
    assert response.message.content == "hi"
    assert response.usage.total_tokens == 8
    assert provider.name == "mock-chat"


@pytest.mark.asyncio
async def test_openai_chat_uses_model_code_when_no_model_id():
    """未配置 model_id 时请求体使用 model_code 作为厂商模型 ID"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = request.content.decode()
        return httpx.Response(200, json={"id": "1", "choices": [{"message": {"content": "ok"}}]})

    provider = OpenAICompatibleProvider(
        _config(model_id=None),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await provider.chat(ChatRequest(model="mock-chat", messages=[]))
    assert '"model":"mock-chat"' in captured["payload"]


@pytest.mark.asyncio
async def test_openai_stream_parses_sse():
    """流式 SSE 逐行解析 delta/finish_reason/usage"""
    sse = (
        'data: {"id":"1","choices":[{"index":0,"delta":{"role":"assistant","content":"hello"},"finish_reason":null}]}\n\n'
        'data: {"id":"1","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":5,"completion_tokens":3,"total_tokens":8}}\n\n'
        "data: [DONE]\n"
    )
    provider = OpenAICompatibleProvider(
        _config(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=sse))),
    )
    chunks = [chunk async for chunk in provider.stream_chat(ChatRequest(model="mock-chat", messages=[]))]
    assert chunks[0].delta == "hello"
    assert chunks[-1].finish_reason is not None
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 8


@pytest.mark.asyncio
async def test_openai_embedding():
    """向量化调用 /embeddings 并映射统一结构"""
    provider = _provider(
        {
            "model": "mock-chat",
            "data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}],
            "usage": {"prompt_tokens": 10, "total_tokens": 10},
        }
    )
    response = await provider.embedding(EmbeddingRequest(model="mock-chat", input="hi"))
    assert response.embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert response.usage.prompt_tokens == 10


@pytest.mark.asyncio
async def test_openai_rate_limited_maps_error():
    """429 -> E3-THIRD-003 限流错误码"""
    provider = OpenAICompatibleProvider(
        _config(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429))),
    )
    with pytest.raises(BizException) as exc_info:
        await provider.chat(ChatRequest(model="mock-chat", messages=[]))
    assert exc_info.value.code == "E3-THIRD-003"


@pytest.mark.asyncio
async def test_openai_timeout_maps_error():
    """超时 -> E3-THIRD-002 超时错误码"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    provider = OpenAICompatibleProvider(
        _config(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(BizException) as exc_info:
        await provider.chat(ChatRequest(model="mock-chat", messages=[]))
    assert exc_info.value.code == "E3-THIRD-002"


# ------------------------------------------------------------------
# ModelProviderFactory 协议构建器
# ------------------------------------------------------------------


def test_factory_falls_back_to_openai_compatible():
    """未注册的自定义协议回落 OpenAI 兼容默认协议（规范 §17.4）"""
    provider = ModelProviderFactory.create(_config(provider="private-gateway"))
    assert isinstance(provider, OpenAICompatibleProvider)


def test_factory_uses_registered_custom_provider(clean_factory):
    """注册自定义供应商工厂后按 provider 字段自动装配（供应商 SPI，规范 §2.1）"""

    class DummyProvider(OpenAICompatibleProvider):
        name = "dummy"

    ModelProviderFactory.register_factory("custom", lambda config: DummyProvider(config))
    provider = ModelProviderFactory.create(_config(provider="custom"))
    assert isinstance(provider, DummyProvider)


# ------------------------------------------------------------------
# ModelAutoRegistrar 自动注册
# ------------------------------------------------------------------


def test_registrar_from_dicts_filters_extra_fields():
    """yml 配置清单转换：过滤展示字段、provider 缺省回落"""
    configs = ModelAutoRegistrar.from_dicts(
        [
            {
                "id": 1,
                "model_name": "DeepSeek Chat",
                "model_code": "deepseek-chat",
                "api_base": "https://api.deepseek.com/v1",
                "api_key": "sk-1",
                "scene": "chat",  # 非 ModelConfig 字段，应被过滤
            }
        ]
    )
    assert len(configs) == 1
    assert configs[0].provider == "openai_compatible"
    assert configs[0].model_code == "deepseek-chat"


def test_registrar_auto_registers_to_spi(clean_registry):
    """按配置清单自动注册供应商进 SPI 注册表，业务代码无需手动 register"""
    registrar = ModelAutoRegistrar()
    registered = registrar.register_configs([_config()])
    assert registered == ["mock-chat"]
    assert ModelProviderRegistry.contains("mock-chat")
    provider = ModelProviderRegistry.get("mock-chat")
    assert isinstance(provider, OpenAICompatibleProvider)


@pytest.mark.asyncio
async def test_registrar_register_from_store(clean_registry):
    """从模型配置来源 SPI（页面化配置）自动同步注册"""
    store = DictModelConfigStore(
        {
            "mock-chat": _config(),
            "mock-embed": _config(id=2, model_code="mock-embed", model_id="embed-1"),
        }
    )
    registrar = ModelAutoRegistrar()
    registered = await registrar.register_from_store(store)
    assert set(registered) == {"mock-chat", "mock-embed"}
    assert ModelProviderRegistry.contains("mock-embed")


@pytest.mark.asyncio
async def test_registrar_close_releases_providers(clean_registry):
    """close 释放自动注册创建的供应商客户端"""
    registrar = ModelAutoRegistrar()
    registrar.register_configs([_config()])
    await registrar.close()  # 不应抛错


# ------------------------------------------------------------------
# application 装配闭环
# ------------------------------------------------------------------


def _ai_settings(provider: str = "openai_compatible") -> dict:
    """构造启用 AI 的应用配置（yml app.ai.models 等价物）"""
    return {
        "app": {
            "ai": {
                "enabled": True,
                "models": [
                    {
                        "id": 1,
                        "model_name": "Mock Chat",
                        "model_code": "m1",
                        "provider": provider,
                        "api_base": API_BASE,
                        "api_key": "sk-test",
                    }
                ],
                "model_gateway": {"default_scene": "chat", "routes": {"chat": {"primary": "m1", "backups": []}}},
            }
        }
    }


def test_application_auto_registers_models(clean_registry):
    """application 装配：yml models 自动注册供应商，网关与注册器组件就绪"""
    app = create_app(_ai_settings())
    assert ModelProviderRegistry.contains("m1")
    assert isinstance(app.state.ai, ModelGateway)
    assert isinstance(app.state.ai_registrar, ModelAutoRegistrar)


@pytest.mark.asyncio
async def test_application_gateway_chat_after_auto_register(clean_registry, clean_factory):
    """装配闭环：配置驱动自动注册后，模型网关可按场景调用（供应商经自定义工厂注入）"""

    class FakeOpenAI(OpenAICompatibleProvider):
        """可控 OpenAI 兼容供应商（避免真实网络）"""

        async def chat(self, request: ChatRequest):
            return await super().chat(request)

    # 供应商 SPI：自定义工厂返回绑定 MockTransport 的实例
    def fake_factory(config: ModelConfig) -> FakeOpenAI:
        return FakeOpenAI(
            config,
            client=httpx.AsyncClient(
                transport=_json_handler(
                    {
                        "id": "1",
                        "model": "m1",
                        "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    }
                )
            ),
        )

    ModelProviderFactory.register_factory("openai_compatible", fake_factory)
    app = create_app(_ai_settings())
    gateway = app.state.ai
    response = await gateway.chat(ChatRequest(model="m1", messages=[ChatMessage(role=ChatRole.USER, content="hi")]), scene="chat")
    assert response.message.content == "ok"


# ------------------------------------------------------------------
# fetch_remote_models（AI-10 页面化配置动态获取模型列表）
# ------------------------------------------------------------------


class _FakeHttpClient:
    """记录请求并返回固定响应的假客户端（不依赖第三方 mock 库，仅暴露 async get）"""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.calls: list[tuple[str, dict | None]] = []

    async def get(self, url: str, headers: dict | None = None) -> httpx.Response:
        self.calls.append((url, headers))
        return self._response


@pytest.mark.asyncio
async def test_fetch_remote_models_parses_data_ids():
    """AI-10：/models 响应 data[].id 解析为模型 ID 列表，并携带 Bearer 鉴权头"""
    client = _FakeHttpClient(
        httpx.Response(200, json={"object": "list", "data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]})
    )
    registrar = ModelAutoRegistrar()
    ids = await registrar.fetch_remote_models("https://api.deepseek.com/v1", "sk-remote", client)
    assert ids == ["deepseek-chat", "deepseek-reasoner"]
    url, headers = client.calls[0]
    assert url == "https://api.deepseek.com/v1/models"
    assert headers == {"Authorization": "Bearer sk-remote"}


@pytest.mark.asyncio
async def test_fetch_remote_models_trims_trailing_slash():
    """AI-10：provider_url 尾部斜杠不影响 /models 拼接"""
    client = _FakeHttpClient(httpx.Response(200, json={"data": [{"id": "m1"}]}))
    registrar = ModelAutoRegistrar()
    await registrar.fetch_remote_models("https://api.deepseek.com/v1/", "sk-remote", client)
    assert client.calls[0][0] == "https://api.deepseek.com/v1/models"


@pytest.mark.asyncio
async def test_fetch_remote_models_http_error_degrades_to_empty():
    """AI-10：非 2xx 响应降级为空列表且不抛异常"""
    client = _FakeHttpClient(httpx.Response(500, json={"error": "boom"}))
    registrar = ModelAutoRegistrar()
    assert await registrar.fetch_remote_models("https://api.deepseek.com/v1", "sk-remote", client) == []


@pytest.mark.asyncio
async def test_fetch_remote_models_network_error_degrades_to_empty():
    """AI-10：网络异常降级为空列表且不抛异常"""

    class _ErrorClient(_FakeHttpClient):
        async def get(self, url: str, headers: dict | None = None) -> httpx.Response:
            raise httpx.ConnectError("network down")

    registrar = ModelAutoRegistrar()
    assert await registrar.fetch_remote_models("https://api.deepseek.com/v1", "sk-remote", _ErrorClient(httpx.Response(200))) == []


@pytest.mark.asyncio
async def test_fetch_remote_models_filters_malformed_items():
    """AI-10：data 中缺 id / 非 dict 项被过滤，保持顺序"""
    client = _FakeHttpClient(httpx.Response(200, json={"data": [{"id": "a"}, {"name": "b"}, "c", None, {"id": ""}]}))
    registrar = ModelAutoRegistrar()
    assert await registrar.fetch_remote_models("https://api.deepseek.com/v1", "sk-remote", client) == ["a"]


@pytest.mark.asyncio
async def test_fetch_remote_models_malformed_payload_degrades_to_empty():
    """AI-10：响应体缺 data 数组或非 JSON 时降级为空列表"""
    registrar = ModelAutoRegistrar()
    bad_payload_client = _FakeHttpClient(httpx.Response(200, json={"error": "no data"}))
    assert await registrar.fetch_remote_models("https://api.deepseek.com/v1", "sk-remote", bad_payload_client) == []
    bad_json_client = _FakeHttpClient(httpx.Response(200, text="<html>not json</html>"))
    assert await registrar.fetch_remote_models("https://api.deepseek.com/v1", "sk-remote", bad_json_client) == []
