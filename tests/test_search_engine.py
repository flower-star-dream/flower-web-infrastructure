"""
搜索引擎模块测试（InMemory 默认实现 + 错误码 + 注册表 + 配置）

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 覆盖 SearchEngineInterface 内存默认实现全方法（索引生命周期/写入/删除/检索/
              分页/高亮/租户隔离/容量上限）、模型校验、错误码登记、注册表与配置装配。
              全部内存执行，不触网、不依赖 es extra。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from web_infra.context import RequestContext
from web_infra.error import ErrorCodeRegistry
from web_infra.search import (
    SearchConfig,
    SearchEngineRegistry,
    SearchErrorCode,
    SearchErrorCodeEnum,
    SearchQuery,
    InMemorySearchEngine,
)
from web_infra.search.in_memory_search_engine import tokenize


@pytest.fixture
def engine() -> InMemorySearchEngine:
    """内存搜索引擎实例（不设容量上限）"""
    return InMemorySearchEngine()


def _q(keyword: str, **kwargs) -> SearchQuery:
    """构造检索参数（默认指向测试索引 products）"""
    return SearchQuery(keyword=keyword, index_name="products", **kwargs)


# ----------------------------------------------------------------------
# 分词
# ----------------------------------------------------------------------


def test_tokenize_mixed():
    """分词：中文按单字、英文按单词（小写）、数字整体、大小写归一"""
    assert tokenize("Hello 世界 123") == ["hello", "世", "界", "123"]
    assert tokenize("苹果Apple") == ["苹", "果", "apple"]
    assert tokenize("") == []


# ----------------------------------------------------------------------
# 索引生命周期
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_delete_index_idempotent(engine):
    """创建/删除索引幂等（内存无物理索引，重复调用不报错）"""
    await engine.create_index("t1", "products")
    await engine.create_index("t1", "products")
    await engine.delete_index("t1", "products")
    await engine.delete_index("t1", "products")


@pytest.mark.asyncio
async def test_create_index_validate_namespace(engine):
    """命名空间参数校验：空租户回落 no-tenant（可选语义），下划线/空索引名拒绝"""
    # 空/未传租户：回落 no-tenant 占位，正常执行
    await engine.create_index(None, "products")
    await engine.create_index("", "products")
    # 下划线租户/空索引名：拒绝（命名空间分隔符保留）
    with pytest.raises(ValueError):
        await engine.create_index("t_1", "products")
    with pytest.raises(ValueError):
        await engine.create_index("t1", "")


# ----------------------------------------------------------------------
# 写入与删除
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_document_overwrite(engine):
    """单条写入与覆盖：同名 doc_id 全量替换，旧倒排清理"""
    await engine.index_document("t1", "products", "p1", {"title": "苹果手机"})
    hits = await engine.search("t1", _q("苹果"))
    assert [h.id for h in hits] == ["p1"]
    # 覆盖：旧内容关键词不再命中
    await engine.index_document("t1", "products", "p1", {"title": "华为平板"})
    hits = await engine.search("t1", _q("苹果"))
    assert hits == []
    hits = await engine.search("t1", _q("华为"))
    assert [h.id for h in hits] == ["p1"]


@pytest.mark.asyncio
async def test_bulk_index_skip_missing_id(engine):
    """批量写入：缺 id 的项跳过（不中断整批）"""
    await engine.bulk_index(
        "t1",
        "products",
        [
            {"id": "p1", "title": "苹果手机"},
            {"title": "无 id 文档"},
            {"id": "p2", "title": "华为手机"},
        ],
    )
    hits = await engine.search("t1", _q("手机"))
    assert sorted(h.id for h in hits) == ["p1", "p2"]


@pytest.mark.asyncio
async def test_delete_document(engine):
    """删除文档（幂等：不存在时静默）"""
    await engine.index_document("t1", "products", "p1", {"title": "苹果手机"})
    await engine.delete_document("t1", "products", "p1")
    await engine.delete_document("t1", "products", "p1")  # 幂等
    hits = await engine.search("t1", _q("苹果"))
    assert hits == []


# ----------------------------------------------------------------------
# 检索
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_ranking(engine):
    """相关性与得分排序：重复关键词的文档得分更高"""
    await engine.bulk_index(
        "t1",
        "products",
        [
            {"id": "p1", "title": "苹果手机 苹果"},
            {"id": "p2", "title": "华为手机"},
            {"id": "p3", "title": "苹果电脑"},
        ],
    )
    hits = await engine.search("t1", _q("苹果"))
    assert [h.id for h in hits] == ["p1", "p3"]
    assert hits[0].score > hits[1].score


@pytest.mark.asyncio
async def test_search_pagination(engine):
    """分页：offset/size 截断"""
    await engine.bulk_index(
        "t1", "products", [{"id": f"p{i}", "title": f"苹果 {i}"} for i in range(5)]
    )
    hits = await engine.search("t1", _q("苹果", offset=1, size=2))
    assert [h.id for h in hits] == ["p1", "p2"]


@pytest.mark.asyncio
async def test_search_highlight(engine):
    """高亮：命中 token 以 <em> 包裹（中文单字各自高亮）"""
    await engine.index_document("t1", "products", "p1", {"title": "苹果手机"})
    hits = await engine.search("t1", _q("苹果", highlight=True))
    assert hits[0].highlight["title"] == ["<em>苹</em><em>果</em>手机"]
    # 未开启高亮：空字典
    hits = await engine.search("t1", _q("苹果"))
    assert hits[0].highlight == {}


@pytest.mark.asyncio
async def test_search_no_hit(engine):
    """无命中返回空列表"""
    await engine.index_document("t1", "products", "p1", {"title": "苹果手机"})
    hits = await engine.search("t1", _q("不存在词"))
    assert hits == []


@pytest.mark.asyncio
async def test_search_tenant_isolation(engine):
    """租户隔离：不同租户数据互不可见"""
    await engine.index_document("t1", "products", "p1", {"title": "苹果手机"})
    await engine.index_document("t2", "products", "p2", {"title": "华为手机"})
    hits = await engine.search("t1", _q("手机"))
    assert [h.id for h in hits] == ["p1"]
    hits = await engine.search("t2", _q("手机"))
    assert [h.id for h in hits] == ["p2"]


@pytest.mark.asyncio
async def test_tenant_optional_reads_context(engine):
    """tenant_id 可选：缺省从请求上下文（RequestContext）读取"""
    RequestContext.set_tenant_id("t1")
    try:
        await engine.index_document(None, "products", "p1", {"title": "苹果手机"})
    finally:
        RequestContext.clear()
    hits = await engine.search("t1", _q("苹果"))
    assert [h.id for h in hits] == ["p1"]
    # 无租户上下文（no-tenant）检索不到 t1 数据
    hits = await engine.search(None, _q("苹果"))
    assert hits == []


@pytest.mark.asyncio
async def test_tenant_optional_defaults_placeholder(engine):
    """tenant_id 可选：无上下文且不传租户 → no-tenant 占位命名空间（单租户数据收敛，隔离退化为全局共享）"""
    await engine.index_document(None, "products", "p1", {"title": "苹果手机"})
    hits = await engine.search(None, _q("苹果"))
    assert [h.id for h in hits] == ["p1"]
    # 显式 no-tenant 与缺省解析结果一致
    hits = await engine.search("no-tenant", _q("苹果"))
    assert [h.id for h in hits] == ["p1"]


@pytest.mark.asyncio
async def test_search_index_isolation(engine):
    """索引隔离：同租户不同索引数据互不可见"""
    await engine.index_document("t1", "products", "p1", {"title": "苹果手机"})
    await engine.index_document("t1", "articles", "a1", {"title": "苹果新闻"})
    hits = await engine.search("t1", _q("苹果"))
    assert [h.id for h in hits] == ["p1"]
    # 查询另一索引：仅命中该索引数据
    hits = await engine.search("t1", SearchQuery(keyword="苹果", index_name="articles"))
    assert [h.id for h in hits] == ["a1"]


# ----------------------------------------------------------------------
# 容量上限
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capacity_limit_evict_oldest():
    """容量上限：超限后按写入顺序淘汰最旧文档"""
    engine = InMemorySearchEngine(max_documents_per_tenant=2)
    await engine.bulk_index(
        "t1", "products", [{"id": f"p{i}", "title": f"苹果 {i}"} for i in range(3)]
    )
    hits = await engine.search("t1", _q("苹果"))
    assert sorted(h.id for h in hits) == ["p1", "p2"]


# ----------------------------------------------------------------------
# 模型校验
# ----------------------------------------------------------------------


def test_search_query_validation():
    """检索参数校验：空关键词/负数偏移/超限 size 拒绝"""
    with pytest.raises(ValidationError):
        SearchQuery(keyword="")
    with pytest.raises(ValidationError):
        SearchQuery(keyword="x", offset=-1)
    with pytest.raises(ValidationError):
        SearchQuery(keyword="x", size=0)
    with pytest.raises(ValidationError):
        SearchQuery(keyword="x", size=101)


def test_search_query_defaults():
    """检索参数默认值：默认索引名/分页"""
    query = SearchQuery(keyword="苹果")
    assert query.index_name == "default"
    assert query.offset == 0
    assert query.size == 10
    assert query.highlight is False


# ----------------------------------------------------------------------
# 错误码
# ----------------------------------------------------------------------


def test_search_error_code_registered():
    """错误码登记：E3-SRCH/E4-SRCH 可经注册表解析，语义符合规范（E3 可重试）"""
    code = ErrorCodeRegistry.get("E3-SRCH-000")
    assert code is not None and code.retryable
    assert ErrorCodeRegistry.get("E3-SRCH-001").retryable
    assert ErrorCodeRegistry.get("E4-SRCH-001").retryable is False
    assert SearchErrorCodeEnum.of("E3-SRCH-000") is SearchErrorCodeEnum.SEARCH_ENGINE_ERROR
    assert SearchErrorCodeEnum.of("E3-SRCH-999") is None
    # 对外类属性与枚举值一致
    assert SearchErrorCode.SEARCH_NOT_CONFIGURED.code == "E4-SRCH-001"


# ----------------------------------------------------------------------
# 注册表与配置
# ----------------------------------------------------------------------


def test_registry_builtin_entries():
    """内置注册条目：memory 可实例化，elasticsearch 已登记（不实例化避免触发 es 依赖）"""
    assert "memory" in SearchEngineRegistry.registered_names()
    assert "elasticsearch" in SearchEngineRegistry.registered_names()
    engine = SearchEngineRegistry.create("memory", None)  # type: ignore[arg-type]
    assert isinstance(engine, InMemorySearchEngine)


def test_registry_unregister():
    """注销后按名查询抛 KeyError"""
    SearchEngineRegistry.register("test-custom", lambda settings: InMemorySearchEngine())
    assert "test-custom" in SearchEngineRegistry.registered_names()
    SearchEngineRegistry.unregister("test-custom")
    with pytest.raises(KeyError):
        SearchEngineRegistry.get("test-custom")


def test_search_config_defaults():
    """配置模型默认值：memory 类型 / 默认索引前缀 / ES hosts 归一化"""
    config = SearchConfig()
    assert config.type == "memory"
    assert config.index_prefix == "web"
    assert config.elasticsearch.resolve_hosts() == ["http://localhost:9200"]
    # hosts 字符串逗号分隔归一化
    config = SearchConfig(elasticsearch={"hosts": "http://a:9200, http://b:9200"})
    assert config.elasticsearch.resolve_hosts() == ["http://a:9200", "http://b:9200"]
