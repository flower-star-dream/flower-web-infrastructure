"""
搜索引擎业务常量类

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 搜索引擎域常量（搜索引擎接入计划 v0.2.0）：错误码域前缀、索引命名默认值、
              检索分页默认值、高亮标签。索引真实命名规则由实现方按
              {index_prefix}_{tenant_id}_{index_name} 生成（全文）与 {index_prefix}_{tenant_id}_vector（向量）。
"""
from __future__ import annotations


class SearchConstant:
    """搜索引擎业务常量（索引命名 / 分页 / 高亮 / 错误码域）"""

    # 错误码域前缀（E3-SRCH / E4-SRCH）
    ERROR_DOMAIN = "SRCH"

    # 索引前缀默认值（app.search.index_prefix 缺省；真实索引名前缀，按部署环境可覆盖）
    DEFAULT_INDEX_PREFIX = "web"

    # 默认业务索引名（app.search 未指定索引名时的兜底）
    DEFAULT_INDEX_NAME = "default"

    # 向量索引业务名（ElasticsearchVectorStore 的命名空间后缀，避免与全文索引混淆）
    VECTOR_INDEX_NAME = "vector"

    # 检索分页默认值（对齐 ES from/size）
    DEFAULT_PAGE_SIZE = 10
    MAX_PAGE_SIZE = 100

    # 高亮标签（InMemory 默认实现与 ES 实现统一，避免业务层依赖实现差异）
    HIGHLIGHT_PRE_TAG = "<em>"
    HIGHLIGHT_POST_TAG = "</em>"

    # BM25 简化打分参数（InMemory 默认实现，与 Lucene/ES 默认一致）
    BM25_K1 = 1.2
    BM25_B = 0.75
