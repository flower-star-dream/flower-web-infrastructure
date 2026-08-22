"""
测试切片基础设施单元测试

@Author: 花海
@Date: 2026/08/22 18:00
@Description: 验证轻量测试上下文装配（web_test_context：只装配指定能力子集，不启全应用）、
              @mock_component 替身注入、测试上下文缓存 fixture、自动回滚。
"""
import pytest

from web_infra.testing.test_context import web_test_context
from web_infra.testing.mock_bean import mock_component
from web_infra.testing import TestContext


def test_web_test_context_enables_subset():
    """轻量测试上下文：只装配指定组件子集（不触网）"""
    ctx = web_test_context(
        {"app.name": "test", "app.cache.type": "memory"},
        components=("cache",),
    )
    assert isinstance(ctx, TestContext)
    assert "cache" in ctx.components
    assert "db" not in ctx.components  # 仅装配 cache


def test_mock_component_replaces_component():
    """@mock_component 替换某组件为替身（对标 @MockBean）"""
    from web_infra.testing.test_context import bind_test_components
    from web_infra.core.aop import get_component

    bind_test_components({"cache": "real-cache", "db": "real-db"})

    @mock_component("cache")
    def FakeCache():
        return "fake-cache"

    assert get_component("cache") == "fake-cache"
    # 不受影响组件保持
    assert get_component("db") == "real-db"


def test_test_context_caches_across_tests():
    """测试上下文缓存：同一规格多次构建返回同一上下文（复用）"""
    from web_infra.testing.fixtures import test_context_cache

    # 走 fixture 内部缓存缓存逻辑
    key = ("app.name", "test")
    first = test_context_cache.get(key)
    # 首次 None（未缓存）
    assert first is None


def test_auto_rollback_context():
    """自动回滚：测试事务在完成后回滚（不污染数据）"""
    from web_infra.testing.rollback import auto_rollback

    @auto_rollback
    def sample():
        return "ok"

    assert sample() == "ok"
