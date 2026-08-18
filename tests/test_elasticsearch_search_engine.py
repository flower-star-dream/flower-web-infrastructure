"""
Elasticsearch 全文搜索引擎测试

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 覆盖 ElasticsearchSearchEngine（elasticsearch-dsl 生产实现）的请求构造
              （索引创建 body / 写入 / 批量 / 删除 / 检索 query / 高亮）、租户前缀隔离、
              幂等与错误码抛转（E3-SRCH / E4-SRCH）。注入 fake AsyncElasticsearch 客户端
              拦截调用并回放预设响应，不触网、不起真实 ES。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("elasticsearch")

from elasticsearch import BadRequestError, NotFoundError  # noqa: E402

from web_infra.infra.error import BizException  # noqa: E402
from web_infra.capabilities.search import ElasticsearchSearchEngine, SearchErrorCode, SearchQuery  # noqa: E402
from web_infra.capabilities.search.search_hit import SearchHit  # noqa: E402

# 租户/索引隔离命名断言
INDEX_NAME = "web_t1_products"
PREFIX = "web"


class _BodyResponse:
    """模拟 elasticsearch-py 8.x 响应对象（ObjectApiResponse：携带 body 字典）"""

    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body


def _es_error(exc_type: type, message: str, status: int, error_type: str) -> Exception:
    """构造 elasticsearch-py ApiError（meta 仅需 status；body 供 __str__ 提取错误类型）"""
    body: dict[str, Any] = {"error": {"root_cause": [{"reason": error_type}], "type": error_type}}
    return exc_type(message, SimpleNamespace(status=status), body)


class _FakeIndices:
    """fake ES indices API（记录 create/delete 调用；可配置抛错）"""

    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []
        self.create_error: Exception | None = None

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        if self.create_error is not None:
            raise self.create_error
        self.create_calls.append(kwargs)
        return {"acknowledged": True, "index": kwargs.get("index", "")}

    async def delete(self, **kwargs: Any) -> dict[str, Any]:
        self.delete_calls.append(kwargs)
        return {"acknowledged": True}


class _FakeAsyncClient:
    """fake AsyncElasticsearch 客户端（记录 index/bulk/delete/search；回放预设响应）"""

    def __init__(self) -> None:
        self.indices = _FakeIndices()
        self.index_calls: list[dict[str, Any]] = []
        self.bulk_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []
        self.search_response: dict[str, Any] | None = None
        self.search_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.closed = False

    async def index(self, **kwargs: Any) -> dict[str, Any]:
        self.index_calls.append(kwargs)
        return {"result": "created"}

    async def bulk(self, **kwargs: Any) -> dict[str, Any]:
        self.bulk_calls.append(kwargs)
        return {"errors": False, "items": []}

    async def delete(self, **kwargs: Any) -> dict[str, Any]:
        if self.delete_error is not None:
            raise self.delete_error
        self.delete_calls.append(kwargs)
        return {"result": "deleted"}

    async def search(self, **kwargs: Any) -> _BodyResponse:
        self.search_calls.append(kwargs)
        if self.search_error is not None:
            raise self.search_error
        return _BodyResponse(self.search_response or {"hits": {"hits": []}})

    async def close(self) -> None:
        self.closed = True


def _make_engine(client: _FakeAsyncClient) -> ElasticsearchSearchEngine:
    """构造注入 fake 客户端的 ES 搜索引擎（index_prefix=web）"""
    return ElasticsearchSearchEngine(index_prefix=PREFIX, client=client)


def _search_response(*hits: dict[str, Any]) -> dict[str, Any]:
    """构造 ES search 响应（hits 结构对齐真实响应）"""
    return {
        "took": 1,
        "timed_out": False,
        "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
        "hits": {
            "total": {"value": len(hits), "relation": "eq"},
            "max_score": 1.0,
            "hits": list(hits),
        },
    }


def _hit(doc_id: str, score: float, source: dict[str, Any], highlight: dict[str, Any] | None = None) -> dict[str, Any]:
    """构造单个 ES hit（_source + 可选 highlight）"""
    hit: dict[str, Any] = {"_index": INDEX_NAME, "_id": doc_id, "_score": score, "_source": source}
    if highlight is not None:
        hit["highlight"] = highlight
    return hit


# ----------------------------------------------------------------------
# 租户前缀隔离
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_index_prefix():
    """租户前缀隔离：真实索引名 {prefix}_{tenant}_{index}，禁止下划线"""
    engine = _make_engine(_FakeAsyncClient())
    assert engine._index_name("t1", "products") == "web_t1_products"
    with pytest.raises(ValueError):
        engine._index_name("t_1", "products")
    with pytest.raises(ValueError):
        engine._index_name("t1", "")


@pytest.mark.asyncio
async def test_tenant_optional_reads_context():
    """tenant_id 可选：缺省从请求上下文读取 → 索引名 web_t1_products"""
    from web_infra.infra.context import RequestContext

    client = _FakeAsyncClient()
    engine = _make_engine(client)
    RequestContext.set_tenant_id("t1")
    try:
        await engine.index_document(None, "products", "p1", {"title": "苹果手机"})
    finally:
        RequestContext.clear()
    call = client.index_calls[0]
    assert call["index"] == INDEX_NAME


# ----------------------------------------------------------------------
# 索引生命周期
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_index_body():
    """创建索引：默认 settings + 业务自定义 mappings/settings 透传"""
    client = _FakeAsyncClient()
    engine = _make_engine(client)
    await engine.create_index(
        "t1",
        "products",
        mappings={"properties": {"title": {"type": "text", "analyzer": "ik_max_word"}}},
        settings={"number_of_replicas": 1},
    )
    call = client.indices.create_calls[0]
    assert call["index"] == INDEX_NAME
    assert call["body"]["settings"]["number_of_shards"] == 1  # 默认
    assert call["body"]["settings"]["number_of_replicas"] == 1  # 业务覆盖
    assert call["body"]["mappings"]["properties"]["title"]["analyzer"] == "ik_max_word"


@pytest.mark.asyncio
async def test_create_index_idempotent():
    """创建索引幂等：已存在（resource_already_exists_exception）忽略，其他错误转 E3-SRCH-001"""
    client = _FakeAsyncClient()
    engine = _make_engine(client)
    # 已存在：幂等忽略
    client.indices.create_error = _es_error(BadRequestError, "index exists", 400, "resource_already_exists_exception")
    await engine.create_index("t1", "products")
    # 其他错误：抛 E3-SRCH-001
    client.indices.create_error = _es_error(BadRequestError, "bad", 400, "mapper_parsing_exception")
    with pytest.raises(BizException) as exc_info:
        await engine.create_index("t1", "products")
    assert exc_info.value.error_code == SearchErrorCode.SEARCH_INDEX_ERROR


@pytest.mark.asyncio
async def test_delete_index():
    """删除索引：ignore_status=[404] 幂等，调用转发"""
    client = _FakeAsyncClient()
    engine = _make_engine(client)
    await engine.delete_index("t1", "products")
    call = client.indices.delete_calls[0]
    assert call["index"] == INDEX_NAME
    assert call["ignore_status"] == [404]


# ----------------------------------------------------------------------
# 写入
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_document():
    """单条写入：client.index 参数（索引/ID/文档/refresh）"""
    client = _FakeAsyncClient()
    engine = _make_engine(client)
    await engine.index_document("t1", "products", "p1", {"title": "苹果手机"}, refresh=True)
    call = client.index_calls[0]
    assert call["index"] == INDEX_NAME
    assert call["id"] == "p1"
    assert call["document"] == {"title": "苹果手机"}
    assert call["refresh"] is True


@pytest.mark.asyncio
async def test_bulk_index_operations():
    """批量写入：bulk operations 结构（index 动作 + 文档），缺 id 跳过"""
    client = _FakeAsyncClient()
    engine = _make_engine(client)
    await engine.bulk_index(
        "t1",
        "products",
        [
            {"id": "p1", "title": "苹果"},
            {"title": "无 id"},
            {"id": "p2", "title": "华为"},
        ],
    )
    operations = client.bulk_calls[0]["operations"]
    assert operations[0] == {"index": {"_index": INDEX_NAME, "_id": "p1"}}
    assert operations[1] == {"title": "苹果"}
    assert operations[2] == {"index": {"_index": INDEX_NAME, "_id": "p2"}}
    assert operations[3] == {"title": "华为"}
    assert len(operations) == 4  # 缺 id 的项跳过


@pytest.mark.asyncio
async def test_delete_document():
    """删除文档：client.delete 转发；NotFoundError 幂等"""
    client = _FakeAsyncClient()
    engine = _make_engine(client)
    await engine.delete_document("t1", "products", "p1")
    call = client.delete_calls[0]
    assert call["index"] == INDEX_NAME
    assert call["id"] == "p1"
    # 幂等：404 静默
    client.delete_error = _es_error(NotFoundError, "not found", 404, "index_not_found_exception")
    await engine.delete_document("t1", "products", "p1")


# ----------------------------------------------------------------------
# 检索
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_query_body():
    """检索请求：multi_match 全字段 + 分页 from/size + 可选高亮"""
    client = _FakeAsyncClient()
    client.search_response = _search_response(_hit("p1", 1.5, {"title": "苹果手机"}))
    engine = _make_engine(client)
    await engine.search("t1", SearchQuery(keyword="苹果", index_name="products", offset=1, size=5, highlight=True))
    call = client.search_calls[0]
    assert call["index"] == [INDEX_NAME]  # AsyncSearch 的 index 参数为列表形式
    body = call["body"]
    assert body["query"]["multi_match"]["query"] == "苹果"
    assert body["query"]["multi_match"]["fields"] == ["*"]
    assert body["from"] == 1
    assert body["size"] == 5
    # elasticsearch-dsl highlight("*", ...) 的选项落在字段级配置（ES 接受的合法语法）
    field_hl = body["highlight"]["fields"]["*"]
    assert field_hl["require_field_match"] is False
    assert field_hl["pre_tags"] == ["<em>"]
    assert field_hl["post_tags"] == ["</em>"]


@pytest.mark.asyncio
async def test_search_parse_hits():
    """检索响应解析：SearchHit 列表（id/score/source/highlight）"""
    client = _FakeAsyncClient()
    client.search_response = _search_response(
        _hit("p1", 1.5, {"title": "苹果手机"}, {"title": ["<em>苹果</em>手机"]}),
        _hit("p2", 0.8, {"title": "华为手机"}),
    )
    engine = _make_engine(client)
    hits = await engine.search("t1", SearchQuery(keyword="手机", index_name="products"))
    assert isinstance(hits[0], SearchHit)
    assert hits[0].id == "p1"
    assert hits[0].score == 1.5
    assert hits[0].source == {"title": "苹果手机"}
    assert hits[0].highlight["title"] == ["<em>苹果</em>手机"]
    assert hits[1].id == "p2"
    assert hits[1].highlight == {}


@pytest.mark.asyncio
async def test_search_index_not_found_returns_empty():
    """索引不存在：NotFoundError 降级返回空列表（不阻断主流程）"""
    client = _FakeAsyncClient()
    client.search_error = _es_error(NotFoundError, "index not found", 404, "index_not_found_exception")
    engine = _make_engine(client)
    hits = await engine.search("t1", SearchQuery(keyword="苹果", index_name="products"))
    assert hits == []


@pytest.mark.asyncio
async def test_search_engine_error_raise():
    """搜索引擎调用失败：抛 E3-SRCH-000（可重试）"""
    client = _FakeAsyncClient()
    client.search_error = ConnectionError("connection refused")
    engine = _make_engine(client)
    with pytest.raises(BizException) as exc_info:
        await engine.search("t1", SearchQuery(keyword="苹果", index_name="products"))
    assert exc_info.value.error_code == SearchErrorCode.SEARCH_ENGINE_ERROR
    assert exc_info.value.error_code.retryable


# ----------------------------------------------------------------------
# 连接生命周期
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose():
    """关闭连接：aclose 转发 client.close"""
    client = _FakeAsyncClient()
    engine = _make_engine(client)
    await engine.aclose()
    assert client.closed
