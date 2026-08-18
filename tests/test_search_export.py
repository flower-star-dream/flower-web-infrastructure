"""
搜索引擎模块导出冒烟测试

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 搜索引擎为框架顶层导出能力（同 cache/storage 模式，2026-08-18）：
              全文检索 SPI 与内存默认实现随 web_infra 顶层导出（默认实现无外部依赖），
              ES 生产实现经 es extra 延迟导入（未安装 es extra 时导入顶层不报错）。
"""
import importlib

import pytest


def test_top_level_exports():
    """搜索引擎能力随 web_infra 顶层导出（SPI/默认实现/注册表/错误码）"""
    web_infra = importlib.import_module("web_infra")
    assert hasattr(web_infra, "SearchEngineInterface")
    assert hasattr(web_infra, "InMemorySearchEngine")
    assert hasattr(web_infra, "SearchEngineRegistry")
    assert hasattr(web_infra, "SearchErrorCode")
    assert hasattr(web_infra, "SearchQuery")
    assert hasattr(web_infra, "SearchHit")
    assert hasattr(web_infra, "SearchConfig")
    assert hasattr(web_infra, "SearchConstant")
    # ES 生产实现也随顶层导出（构造时才加载 es extra 依赖）
    assert hasattr(web_infra, "ElasticsearchSearchEngine")


def test_top_level_import_star():
    """import * 可导出搜索引擎全部公开名"""
    namespace: dict = {}
    exec("from web_infra import *", namespace)
    assert "SearchEngineInterface" in namespace
    assert "InMemorySearchEngine" in namespace
    assert "SearchEngineRegistry" in namespace
    assert "SearchErrorCode" in namespace


def test_submodule_import_without_es_extra():
    """未安装 es extra 时：顶层与 search 子模块导入不报错（延迟导入契约）"""
    importlib.import_module("web_infra.capabilities.search")
    importlib.import_module("web_infra.capabilities.search.elasticsearch_search_engine")
    importlib.import_module("web_infra.capabilities.ai.retrieval.elasticsearch_vector_store")


def test_ai_retrieval_exports_vector_store():
    """向量检索子模块导出 ES 向量实现（构造时才加载 es extra）"""
    from web_infra.capabilities.ai.retrieval import ElasticsearchVectorStore

    assert ElasticsearchVectorStore is not None
