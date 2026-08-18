"""
Elasticsearch 向量存储测试

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 覆盖 ElasticsearchVectorStore（VectorStoreInterface 生产实现，
              dense_vector + kNN）的请求构造（索引 mapping / bulk / kNN 查询 / mget）、
              租户前缀隔离、幂等与解析。注入 fake Elasticsearch 客户端拦截调用并回放
              预设响应，不触网、不起真实 ES。
"""
from __future__ import annotations

from typing import Any

import pytest

from web_infra.capabilities.ai.retrieval import ElasticsearchVectorStore
from web_infra.capabilities.ai.retrieval.vector_hit import VectorHit

VECTOR_INDEX = "web_t1_vector"
PREFIX = "web"


class _BodyResponse:
    """模拟 elasticsearch-py 8.x 响应对象（ObjectApiResponse：携带 body 字典）"""

    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body


class _SyncFakeIndices:
    """fake ES indices API（exists/create）"""

    def __init__(self) -> None:
        self.exists_result = True
        self.create_calls: list[dict[str, Any]] = []

    def exists(self, **kwargs: Any) -> bool:
        return self.exists_result

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self.create_calls.append(kwargs)
        return {"acknowledged": True, "index": kwargs.get("index", "")}


class _SyncFakeClient:
    """fake Elasticsearch 客户端（记录 bulk/search/mget；回放预设响应）"""

    def __init__(self) -> None:
        self.indices = _SyncFakeIndices()
        self.bulk_calls: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []
        self.mget_result: dict[str, Any] = {"docs": []}
        self.search_response: dict[str, Any] | None = None
        self.closed = False

    def bulk(self, **kwargs: Any) -> dict[str, Any]:
        self.bulk_calls.append(kwargs)
        return {"errors": False, "items": []}

    def search(self, **kwargs: Any) -> _BodyResponse:
        self.search_calls.append(kwargs)
        return _BodyResponse(self.search_response or {"hits": {"hits": []}})

    def mget(self, **kwargs: Any) -> dict[str, Any]:
        return self.mget_result

    def close(self) -> None:
        self.closed = True


def _make_store(client: _SyncFakeClient, dims: int = 4) -> ElasticsearchVectorStore:
    """构造注入 fake 客户端的 ES 向量存储（index_prefix=web，dims=4，num_candidates=50）"""
    return ElasticsearchVectorStore(index_prefix=PREFIX, dims=dims, num_candidates=50, client=client)


# ----------------------------------------------------------------------
# 租户前缀隔离
# ----------------------------------------------------------------------


def test_tenant_index_prefix():
    """租户前缀隔离：{prefix}_{tenant}_vector，禁止下划线"""
    store = _make_store(_SyncFakeClient())
    assert store._index_name("t1") == VECTOR_INDEX
    with pytest.raises(ValueError):
        store._index_name("t_1")


def test_tenant_optional_reads_context():
    """tenant_id 可选：缺省从请求上下文读取 → 索引名 web_t1_vector"""
    from web_infra.infra.context import RequestContext

    client = _SyncFakeClient()
    store = _make_store(client)
    RequestContext.set_tenant_id("t1")
    try:
        store.add(None, ["a"], [[1.0, 0.0, 0.0, 0.0]])
    finally:
        RequestContext.clear()
    operations = client.bulk_calls[0]["operations"]
    assert operations[0] == {"index": {"_index": VECTOR_INDEX, "_id": "a"}}


# ----------------------------------------------------------------------
# 写入
# ----------------------------------------------------------------------


def test_add_ensure_index_and_bulk():
    """写入：自动创建索引（dense_vector dims mapping）+ bulk index operations"""
    client = _SyncFakeClient()
    store = _make_store(client)
    store.add("t1", ["a", "b"], [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
    # 索引创建：dense_vector 维度对齐
    create = client.indices.create_calls[0]
    assert create["index"] == VECTOR_INDEX
    assert create["mappings"]["properties"]["vector"]["type"] == "dense_vector"
    assert create["mappings"]["properties"]["vector"]["dims"] == 4
    assert create["mappings"]["properties"]["vector_id"]["type"] == "keyword"
    assert create["ignore_status"] == [400]  # 幂等
    # bulk 写入：index 动作 + 向量
    operations = client.bulk_calls[0]["operations"]
    assert operations[0] == {"index": {"_index": VECTOR_INDEX, "_id": "a"}}
    assert operations[1] == {"vector": [1.0, 0.0, 0.0, 0.0]}
    assert operations[2] == {"index": {"_index": VECTOR_INDEX, "_id": "b"}}
    assert operations[3] == {"vector": [0.0, 1.0, 0.0, 0.0]}


def test_add_length_mismatch():
    """写入长度不一致拒绝"""
    store = _make_store(_SyncFakeClient())
    with pytest.raises(ValueError):
        store.add("t1", ["a"], [[1.0, 0.0], [0.0, 1.0]])


def test_delete_bulk():
    """删除：bulk delete operations（幂等，不存在的 ID 由 ES 忽略）"""
    client = _SyncFakeClient()
    store = _make_store(client)
    store.delete("t1", ["a", "b"])
    operations = client.bulk_calls[0]["operations"]
    assert operations == [
        {"delete": {"_index": VECTOR_INDEX, "_id": "a"}},
        {"delete": {"_index": VECTOR_INDEX, "_id": "b"}},
    ]


# ----------------------------------------------------------------------
# 检索
# ----------------------------------------------------------------------


def test_search_knn():
    """kNN 检索：extra(knn=...) 请求体 + VectorHit 解析"""
    client = _SyncFakeClient()
    client.search_response = {
        "hits": {
            "total": {"value": 2, "relation": "eq"},
            "max_score": 1.0,
            "hits": [
                {"_index": VECTOR_INDEX, "_id": "a", "_score": 0.95, "_source": {"vector": [1.0, 0.0, 0.0, 0.0]}},
                {"_index": VECTOR_INDEX, "_id": "b", "_score": 0.70, "_source": {"vector": [0.0, 1.0, 0.0, 0.0]}},
            ],
        }
    }
    store = _make_store(client)
    hits = store.search("t1", [0.9, 0.1, 0.0, 0.0], top_k=2)
    body = client.search_calls[0]["body"]
    knn = body["knn"]
    assert knn["field"] == "vector"
    assert knn["query_vector"] == [0.9, 0.1, 0.0, 0.0]
    assert knn["k"] == 2
    assert knn["num_candidates"] == 50
    assert isinstance(hits[0], VectorHit)
    assert [h.id for h in hits] == ["a", "b"]
    assert hits[0].score == 0.95
    assert hits[0].vector == [1.0, 0.0, 0.0, 0.0]


def test_get_mget():
    """按 ID 取回：mget 解析（未找到的 ID 不返回）"""
    client = _SyncFakeClient()
    client.mget_result = {
        "docs": [
            {"_id": "a", "found": True, "_source": {"vector": [1.0, 0.0, 0.0, 0.0]}},
            {"_id": "b", "found": False},
        ]
    }
    store = _make_store(client)
    result = store.get("t1", ["a", "b", "c"])
    assert result == {"a": [1.0, 0.0, 0.0, 0.0]}


def test_ids_in_order():
    """按 _id 升序返回全部向量 ID（邻居扩展定位用）"""
    client = _SyncFakeClient()
    client.search_response = {
        "hits": {
            "hits": [
                {"_id": "a"},
                {"_id": "b"},
            ]
        }
    }
    store = _make_store(client)
    ids = store.ids_in_order("t1")
    assert ids == ["a", "b"]
    call = client.search_calls[0]
    assert call["index"] == VECTOR_INDEX  # 底层 client.search 的 index 为字符串
    assert call["_source"] is False
    assert call["sort"] == ["vector_id"]


# ----------------------------------------------------------------------
# 幂等与边界
# ----------------------------------------------------------------------


def test_index_not_exists_idempotent():
    """索引不存在：delete/get/ids_in_order 幂等返回空"""
    client = _SyncFakeClient()
    client.indices.exists_result = False
    store = _make_store(client)
    store.delete("t1", ["a"])
    assert client.bulk_calls == []
    assert store.get("t1", ["a"]) == {}
    assert store.ids_in_order("t1") == []


def test_auto_create_index_off():
    """关闭自动建索引：写入/检索不触发 indices.create"""
    client = _SyncFakeClient()
    store = ElasticsearchVectorStore(index_prefix=PREFIX, auto_create_index=False, client=client)
    store.add("t1", ["a"], [[1.0, 0.0, 0.0, 0.0]])
    assert client.indices.create_calls == []
    assert client.bulk_calls[0]["operations"][0]["index"]["_index"] == VECTOR_INDEX


def test_close():
    """关闭连接：close 转发 client.close"""
    client = _SyncFakeClient()
    store = _make_store(client)
    store.close()
    assert client.closed
