"""
AI 缓存组件单元测试

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 验证 Key 稳定性、模型版本变更失效、租户隔离与参数参与 Key（AI 规范 §8）。
"""
import pytest

from web_infra.ai import AICache


@pytest.mark.asyncio
async def test_set_get_roundtrip():
    """写入后可读取命中"""
    cache = AICache()
    await cache.set("你好", "你好！", model_code="deepseek", model_version="1.0")
    assert await cache.get("你好", model_code="deepseek", model_version="1.0") == "你好！"


@pytest.mark.asyncio
async def test_same_input_same_key():
    """相同输入（参数一致）命中同一 Key"""
    cache = AICache()
    await cache.set("你好", "A", model_code="m", model_version="1.0", params={"temperature": 0.0})
    assert await cache.get("你好", model_code="m", model_version="1.0", params={"temperature": 0.0}) == "A"


@pytest.mark.asyncio
async def test_model_version_invalidates_cache():
    """模型版本变更后不命中（Key 变化实现自然失效）"""
    cache = AICache()
    await cache.set("你好", "旧版回答", model_code="m", model_version="1.0")
    assert await cache.get("你好", model_code="m", model_version="1.1") is None


@pytest.mark.asyncio
async def test_tenant_isolation():
    """租户隔离：不同租户互不命中"""
    cache = AICache()
    await cache.set("你好", "租户A", model_code="m", model_version="1.0", tenant_id="tenant-a")
    assert await cache.get("你好", model_code="m", model_version="1.0", tenant_id="tenant-a") == "租户A"
    assert await cache.get("你好", model_code="m", model_version="1.0", tenant_id="tenant-b") is None


@pytest.mark.asyncio
async def test_params_affect_key():
    """关键参数参与 Key：参数不同不命中"""
    cache = AICache()
    await cache.set("你好", "低温回答", model_code="m", model_version="1.0", params={"temperature": 0.0})
    assert await cache.get("你好", model_code="m", model_version="1.0", params={"temperature": 0.9}) is None


@pytest.mark.asyncio
async def test_key_uses_sha256_not_md5():
    """Key 使用 SHA-256 前 16 字节且含租户维度（禁 MD5）"""
    cache = AICache()
    key = cache._build_key("你好", "m", "1.0", "tenant-a", None)
    assert key.startswith("web:ai:v1:cache:")
    assert ":tenant-a:" in key  # 租户维度明文可见
    digest = key.split(":")[-1]
    assert len(digest) == 32  # sha256 前 16 字节 = 32 hex
    assert all(c in "0123456789abcdef" for c in digest)


@pytest.mark.asyncio
async def test_user_id_isolation():
    """用户维度隔离：同一 Prompt 不同用户互不命中（防个性化语义跨用户串扰，AI-4）"""
    cache = AICache()
    await cache.set("你好", "用户A回答", model_code="m", model_version="1.0", user_id="user-a")
    assert await cache.get("你好", model_code="m", model_version="1.0", user_id="user-a") == "用户A回答"
    assert await cache.get("你好", model_code="m", model_version="1.0", user_id="user-b") is None


def test_user_id_in_digest_not_prefix():
    """user_id 参与哈希但不进明文前缀（Key 结构 {prefix}{tenant}:{digest} 保持不变）"""
    cache = AICache()
    key_a = cache._build_key("你好", "m", "1.0", "tenant-a", None, user_id="u1")
    key_b = cache._build_key("你好", "m", "1.0", "tenant-a", None, user_id="u2")
    assert key_a != key_b  # 用户维度影响摘要
    assert key_a.startswith("web:ai:v1:cache:tenant-a:")
    assert ":u1:" not in key_a  # user_id 不进明文前缀
