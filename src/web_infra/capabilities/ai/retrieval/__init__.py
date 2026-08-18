"""
向量检索模块

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 导出向量检索组件（AI 规范 §11）：文档切片、向量存储、嵌入、重排与检索器。
              含 ES 生产实现（ElasticsearchVectorStore，dense_vector + kNN，es extra 延迟导入：
              未安装 es extra 时导入本模块不报错，构造实例才加载）。
"""
from web_infra.capabilities.ai.retrieval.chunk import Chunk
from web_infra.capabilities.ai.retrieval.document_chunker import DocumentChunkerInterface
from web_infra.capabilities.ai.retrieval.markdown_chunker import MarkdownChunker
from web_infra.capabilities.ai.retrieval.vector_hit import VectorHit
from web_infra.capabilities.ai.retrieval.vector_store_interface import VectorStoreInterface
from web_infra.capabilities.ai.retrieval.in_memory_vector_store import InMemoryVectorStore
from web_infra.capabilities.ai.retrieval.elasticsearch_vector_store import ElasticsearchVectorStore
from web_infra.capabilities.ai.retrieval.embedding_provider import EmbeddingProviderInterface
from web_infra.capabilities.ai.retrieval.reranker import RerankerInterface
from web_infra.capabilities.ai.retrieval.identity_reranker import IdentityReranker
from web_infra.capabilities.ai.retrieval.retrieval_result import RetrievalResult
from web_infra.capabilities.ai.retrieval.retriever import Retriever

__all__ = [
    "Chunk",
    "DocumentChunkerInterface",
    "MarkdownChunker",
    "VectorHit",
    "VectorStoreInterface",
    "InMemoryVectorStore",
    "ElasticsearchVectorStore",
    "EmbeddingProviderInterface",
    "RerankerInterface",
    "IdentityReranker",
    "RetrievalResult",
    "Retriever",
]
