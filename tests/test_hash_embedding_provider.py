"""
哈希特征嵌入提供者测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证 HashEmbeddingProvider（规范 S3-1 扩展点默认实现）：
              确定性（同文本两次结果一致）、维度正确、不同文本向量不同（大概率）、
              批量与单条一致、归一化后值为有限数。
"""
import math

import pytest

from web_infra.ai.retrieval.hash_embedding_provider import HashEmbeddingProvider


def test_embed_is_deterministic():
    """确定性：同文本两次 embed 结果完全一致"""
    provider = HashEmbeddingProvider(dimension=16)
    text = "你好，世界 hello world 2026"
    assert provider.embed(text) == provider.embed(text)


def test_embed_dimension_is_configurable():
    """维度正确：向量长度等于构造参数 dimension"""
    provider = HashEmbeddingProvider(dimension=32)
    assert len(provider.embed("任意文本")) == 32


def test_embed_default_dimension_is_256():
    """默认维度为 256"""
    provider = HashEmbeddingProvider()
    assert len(provider.embed("默认维度")) == 256


def test_different_texts_yield_different_vectors():
    """不同文本大概率得到不同向量（哈希特征区分）"""
    provider = HashEmbeddingProvider(dimension=64)
    vector_a = provider.embed("机器学习与大模型应用实践")
    vector_b = provider.embed("关系数据库优化与索引设计")
    assert vector_a != vector_b


def test_embed_values_are_finite():
    """归一化后所有值为有限数（不出现 NaN/Inf）"""
    provider = HashEmbeddingProvider(dimension=16)
    for value in provider.embed("长文本" * 100):
        assert math.isfinite(value)


def test_embed_batch_matches_single():
    """批量结果与逐条 embed 完全一致（顺序保持）"""
    provider = HashEmbeddingProvider(dimension=16)
    texts = ["第一条文本", "第二条文本", ""]
    batch = provider.embed_batch(texts)
    assert len(batch) == len(texts)
    assert batch[0] == provider.embed(texts[0])
    assert batch[1] == provider.embed(texts[1])
    assert batch[2] == provider.embed(texts[2])


def test_empty_text_returns_zero_vector():
    """空文本返回全 0 向量（长度仍为 dimension）"""
    provider = HashEmbeddingProvider(dimension=16)
    assert provider.embed("") == [0.0] * 16


def test_invalid_dimension_rejected():
    """非正整数维度抛出 ValueError"""
    with pytest.raises(ValueError):
        HashEmbeddingProvider(dimension=0)
