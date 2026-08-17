"""
AI 与大模型扩展模块

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 导出 AI 供应商 SPI、统一出入参结构与 AI 错误码（AI 规范 §2 / §12）。
"""
from web_infra.ai.model_provider_interface import ModelProviderInterface
from web_infra.ai.model_provider_registry import ModelProviderRegistry
from web_infra.ai.model_provider_factory import ModelProviderFactory
from web_infra.ai.model_auto_registrar import ModelAutoRegistrar
from web_infra.ai.provider.openai_compatible_provider import OpenAICompatibleProvider
from web_infra.ai.chat_role_enum import ChatRole
from web_infra.ai.finish_reason_enum import FinishReason
from web_infra.ai.chat_message import ChatMessage
from web_infra.ai.usage import Usage
from web_infra.ai.chat_request import ChatRequest
from web_infra.ai.chat_response import ChatResponse
from web_infra.ai.chat_stream_chunk import ChatStreamChunk
from web_infra.ai.embedding_request import EmbeddingRequest
from web_infra.ai.embedding_response import EmbeddingResponse
from web_infra.error.ai_error_code import AiErrorCode
from web_infra.ai.model_config import ModelConfig
from web_infra.ai.model_config_store_interface import ModelConfigStoreInterface
from web_infra.ai.dict_model_config_store import DictModelConfigStore
from web_infra.ai.model_config_store_registry import ModelConfigStoreRegistry
from web_infra.ai.sqlalchemy_model_config_store import SqlAlchemyModelConfigStore
from web_infra.ai.model_config_manager import ModelConfigManager
from web_infra.ai.prompt.prompt_template import PromptTemplate
from web_infra.ai.prompt.prompt_template_store_interface import PromptTemplateStoreInterface
from web_infra.ai.prompt.in_memory_prompt_template_store import InMemoryPromptTemplateStore
from web_infra.ai.prompt.prompt_template_filler import PromptTemplateFiller
from web_infra.ai.context_window_error_parser import ContextWindowErrorParser
from web_infra.ai.context_truncator import ContextTruncator
from web_infra.ai.context_window_retry import ContextWindowRetryPolicy
from web_infra.ai.retrieval.document_chunker import DocumentChunkerInterface
from web_infra.ai.retrieval.markdown_chunker import MarkdownChunker
from web_infra.ai.retrieval.vector_store_interface import VectorStoreInterface
from web_infra.ai.retrieval.in_memory_vector_store import InMemoryVectorStore
from web_infra.ai.retrieval.embedding_provider import EmbeddingProviderInterface
from web_infra.ai.retrieval.reranker import RerankerInterface
from web_infra.ai.retrieval.retriever import Retriever
from web_infra.ai.guard_action import GuardAction
from web_infra.ai.guard_result import GuardResult
from web_infra.ai.content_guard_interface import ContentGuardInterface
from web_infra.ai.rule_based_content_guard import RuleBasedContentGuard
from web_infra.ai.usage_record import UsageRecord
from web_infra.ai.usage_record_store import UsageRecordStoreInterface
from web_infra.ai.usage_accounting import UsageAccounting
from web_infra.ai.ai_cache import AICache
from web_infra.ai.prompt.prompt_assembler import PromptAssembler
from web_infra.ai.connection_pool.connection_pool_config import ConnectionPoolConfig
from web_infra.ai.connection_pool.connection_pool import ConnectionPoolManager
from web_infra.ai.concurrency.concurrency_guard import ConcurrencyGuard
from web_infra.ai.quota.quota_config import QuotaConfig
from web_infra.ai.quota.quota_store import QuotaCounter, QuotaStoreInterface
from web_infra.ai.quota.in_memory_quota_store import InMemoryQuotaStore
from web_infra.ai.quota.quota_manager import QuotaManager
from web_infra.ai.model_gateway.model_gateway_config import RouteEntry, ModelGatewayConfig
from web_infra.ai.model_gateway.model_router import ModelRouter
from web_infra.ai.model_gateway.model_gateway import ModelGateway

__all__ = [
    "ModelProviderInterface",
    "ModelProviderRegistry",
    "ModelProviderFactory",
    "ModelAutoRegistrar",
    "OpenAICompatibleProvider",
    "ChatRole",
    "FinishReason",
    "ChatMessage",
    "Usage",
    "ChatRequest",
    "ChatResponse",
    "ChatStreamChunk",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "AiErrorCode",
    "ModelConfig",
    "ModelConfigStoreInterface",
    "DictModelConfigStore",
    "ModelConfigStoreRegistry",
    "SqlAlchemyModelConfigStore",
    "ModelConfigManager",
    "PromptTemplate",
    "PromptTemplateStoreInterface",
    "InMemoryPromptTemplateStore",
    "PromptTemplateFiller",
    "ContextWindowErrorParser",
    "ContextTruncator",
    "ContextWindowRetryPolicy",
    "DocumentChunkerInterface",
    "MarkdownChunker",
    "VectorStoreInterface",
    "InMemoryVectorStore",
    "EmbeddingProviderInterface",
    "RerankerInterface",
    "Retriever",
    "GuardAction",
    "GuardResult",
    "ContentGuardInterface",
    "RuleBasedContentGuard",
    "UsageRecord",
    "UsageRecordStoreInterface",
    "UsageAccounting",
    "AICache",
    "PromptAssembler",
    "ConnectionPoolConfig",
    "ConnectionPoolManager",
    "ConcurrencyGuard",
    "QuotaConfig",
    "QuotaCounter",
    "QuotaStoreInterface",
    "InMemoryQuotaStore",
    "QuotaManager",
    "RouteEntry",
    "ModelGatewayConfig",
    "ModelRouter",
    "ModelGateway",
]
