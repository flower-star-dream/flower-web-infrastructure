"""
搜索引擎模块

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 全文搜索引擎 SPI 与实现聚合导出（搜索引擎接入计划 v0.2.0 §3）：统一抽象接口、
              检索参数/命中模型、内存默认实现、ES 生产实现（elasticsearch-dsl，延迟导入）、
              配置与注册表、错误码。业务代码只依赖 SearchEngineInterface；
              默认内存实现保证脚手架派生项目无外部依赖即可运行、单测不触网。
              向量检索经 web_infra.capabilities.ai.retrieval.elasticsearch_vector_store 接入
              VectorStoreInterface（dense_vector + kNN）。
              数据同步（搜索引擎数据同步方案，2026-08-22）：新增 sync 子包（CDC/双写/对账），
              经 web_infra.capabilities.search.sync 主动引入（不随顶层强制加载）。
"""
from web_infra.capabilities.search.elasticsearch_search_engine import ElasticsearchSearchEngine
from web_infra.capabilities.search.in_memory_search_engine import InMemorySearchEngine
from web_infra.capabilities.search.search_config import ElasticsearchSearchConfig, SearchConfig
from web_infra.capabilities.search.search_constant import SearchConstant
from web_infra.capabilities.search.search_engine_interface import SearchEngineInterface
from web_infra.capabilities.search.search_engine_registry import SearchEngineFactory, SearchEngineRegistry
from web_infra.capabilities.search.search_error_code import SearchErrorCode, SearchErrorCodeEnum
from web_infra.capabilities.search.search_hit import SearchHit
from web_infra.capabilities.search.search_query import SearchQuery
from web_infra.capabilities.search import sync as sync

__all__ = [
    "SearchEngineInterface",
    "SearchQuery",
    "SearchHit",
    "InMemorySearchEngine",
    "ElasticsearchSearchEngine",
    "SearchConfig",
    "ElasticsearchSearchConfig",
    "SearchConstant",
    "SearchErrorCode",
    "SearchErrorCodeEnum",
    "SearchEngineFactory",
    "SearchEngineRegistry",
    "sync",
]
