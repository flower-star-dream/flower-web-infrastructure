"""
缓存 Key 模板统一整改测试（S5-3/S5-4）

@Author: 花海
@Date: 2026/08/15
@Description: 验证 CacheKeyBuilder 幂等 Key 模板（INFRA_CACHE_ 规范格式 web:{module}:v1:{biz}，含 v1 版本段），
              以及 redis_idempotency_store / redis_message_idempotency_store 改走统一 builder 生成（禁手写拼接）。
"""
import json

import pytest

from web_infra.constants.cache_key import CacheKeyBuilder
from web_infra.mq.redis_message_idempotency_store import RedisMessageIdempotencyStore
from web_infra.web.redis_idempotency_store import RedisIdempotencyStore
from web_infra.web.idempotency_store_interface import IdempotencyResult


class _FakeRedis:
    """记录 set/get/delete 调用的假 Redis（内存字典 + 调用日志）"""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.sets: list[tuple[str, str, int | None]] = []  # (key, value, ex)

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        self.sets.append((key, value, ex))
        return True

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


# ------------------------------------------------------------------
# CacheKeyBuilder 模板格式
# ------------------------------------------------------------------

def test_idempotency_key_template_contains_v1_and_infra_pattern():
    """幂等占用/结果键符合 web:{module}:v1:{biz} 规范格式且含 v1 版本段（S5-3/S5-4）"""
    occupy = CacheKeyBuilder.idempotency("user-1", "key-001", occupy=True)
    result = CacheKeyBuilder.idempotency("user-1", "key-001", occupy=False)
    assert occupy == "web:idem:v1:occupy:user-1:key-001"
    assert result == "web:idem:v1:result:user-1:key-001"
    # 含版本段 v1，且业务段为「用户 + 幂等键」联合唯一（规范 §12.6）
    assert ":v1:" in occupy and ":v1:" in result


def test_idempotency_key_user_scoped():
    """幂等键按用户维度隔离：不同用户同幂等键生成不同 Key"""
    assert CacheKeyBuilder.idempotency("u-a", "k1") != CacheKeyBuilder.idempotency("u-b", "k1")


def test_message_idempotency_key_template():
    """消息消费幂等键符合规范格式，Topic + MsgId 联合（S5-4 / §9.2）"""
    key = CacheKeyBuilder.message_idempotency("order-topic", "msg-42")
    assert key == "web:mq:v1:msg_idem:order-topic:msg-42"
    assert ":v1:" in key


def test_build_rejects_empty_dynamic_segment():
    """动态段为空抛 ValueError（防生成残缺 Key）"""
    with pytest.raises(ValueError):
        CacheKeyBuilder.build(CacheKeyBuilder.IDEMPOTENCY_OCCUPY, key="   ")


# ------------------------------------------------------------------
# RedisIdempotencyStore 走统一 builder
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redis_idempotency_store_keys_via_builder():
    """Redis 幂等存储的 occupy/result Key 统一经 CacheKeyBuilder 生成（禁手写前缀+key 拼接）"""
    fake = _FakeRedis()
    store = RedisIdempotencyStore(fake)

    assert await store.try_occupy("user-1:key-001", 60) is True
    assert await store.try_occupy("user-1:key-001", 60) is False  # 已占用，NX 失败

    # 占用键：web:idem:v1:occupy:user-1:key-001
    assert "web:idem:v1:occupy:user-1:key-001" in fake.data

    result = IdempotencyResult(status_code=200, content_type="application/json", body=b"{}", request_hash="h1")
    await store.set_result("user-1:key-001", result, 60)
    # 保存结果后：结果键存在、占用键被清除
    assert "web:idem:v1:result:user-1:key-001" in fake.data
    assert "web:idem:v1:occupy:user-1:key-001" not in fake.data

    # 读取结果往返
    loaded = await store.get_result("user-1:key-001")
    assert loaded is not None and loaded.status_code == 200 and loaded.request_hash == "h1"

    # 释放占用
    assert await store.try_occupy("user-1:key-002", 60) is True
    await store.release("user-1:key-002")
    assert "web:idem:v1:occupy:user-1:key-002" not in fake.data


@pytest.mark.asyncio
async def test_redis_idempotency_store_result_payload_roundtrip():
    """结果序列化往返：body 十六进制存储、反序列化还原（连接/序列化逻辑保持原样）"""
    fake = _FakeRedis()
    store = RedisIdempotencyStore(fake)
    result = IdempotencyResult(status_code=201, content_type="text/plain", body=b"hello", request_hash="abc123")
    await store.set_result("u:k", result, 60)

    loaded = await store.get_result("u:k")
    assert loaded is not None
    assert loaded.status_code == 201
    assert loaded.content_type == "text/plain"
    assert loaded.body == b"hello"
    assert loaded.request_hash == "abc123"

    # 序列化载荷为 JSON（键格式变化不影响载荷格式）
    raw = fake.data["web:idem:v1:result:u:k"]
    assert json.loads(raw)["status_code"] == 201


# ------------------------------------------------------------------
# RedisMessageIdempotencyStore 走统一 builder
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redis_message_idempotency_store_key_via_builder():
    """消息消费幂等 Key 统一经 CacheKeyBuilder 生成（禁手写 msg:idem: 前缀）"""
    fake = _FakeRedis()
    store = RedisMessageIdempotencyStore(fake)

    assert await store.try_consume("order-topic:msg-1", 604800) is True
    assert await store.try_consume("order-topic:msg-1", 604800) is False  # 重复消费 NX 失败
    assert "web:mq:v1:msg_idem:order-topic:msg-1" in fake.data
    assert not any(k.startswith("msg:idem:") for k in fake.data)  # 旧前缀不再使用

    await store.release("order-topic:msg-1")
    assert "web:mq:v1:msg_idem:order-topic:msg-1" not in fake.data
