"""
SPI 实例引用（ref:）与运行时切换装配层回归测试

@Author: 花海
@Date: 2026/08/22 12:30
@Description: 验证装配层 _resolve_component 对 'ref:' 实例引用与运行时动态切换的支持：
              create_app 按 app.cache.type=ref:<name> 引用已注册实例；运行时 activate/deactivate
              可观察切换；未注册 ref: 实例快速失败（ConfigError）；fallback 策略组合器在主策略
              未注册时回退 memory 工厂正常返回实现。
"""
from __future__ import annotations

import pytest

from web_infra.core.application import create_app
from web_infra.capabilities.cache import CacheBackendRegistry, CacheConfig, MemoryCacheBackend
from web_infra.infra.config import ConfigError, DictConfigSource, Settings


@pytest.fixture(autouse=True)
def _clean_cache_registry():
    """每用例后清理 CacheBackendRegistry 的实例侧/运行时切换存储，恢复初始快照（工厂存储不动，避免污染其它用例）"""
    before_inst = {ns: dict(entries) for ns, entries in CacheBackendRegistry._inst_store().items()}
    before_active = dict(CacheBackendRegistry._active_store())
    yield
    CacheBackendRegistry._inst_store().clear()
    CacheBackendRegistry._inst_store().update(before_inst)
    CacheBackendRegistry._active_store().clear()
    CacheBackendRegistry._active_store().update(before_active)


def test_ref_wiring_uses_registered_instance():
    """app.cache.type=ref:mycache：装配用已注册实例（app.state.cache / components['cache'] is 实例）"""
    instance = MemoryCacheBackend(CacheConfig(max_size=7))
    CacheBackendRegistry.register_instance("mycache", instance)
    try:
        app = create_app({"app.cache.type": "ref:mycache"})
        assert app.state.cache is instance
        assert app.state.components["cache"] is instance
    finally:
        CacheBackendRegistry.unregister_instance("mycache")


def test_runtime_switch_on_cache_backend_registry():
    """运行时切换：framework/user 同名双实例；activate 重定向解析；deactivate 恢复默认；
    显式 'ns:name' 绕过激活（用 CacheBackendRegistry 验证）"""
    first = MemoryCacheBackend(CacheConfig(max_size=1))
    second = MemoryCacheBackend(CacheConfig(max_size=2))
    CacheBackendRegistry.register_instance(
        "cache1", first, namespace=CacheBackendRegistry.FRAMEWORK_NAMESPACE
    )
    CacheBackendRegistry.register_instance("cache1", second)  # 默认 user 命名空间
    try:
        # 默认 user 优先 → second；显式 framework → first
        assert CacheBackendRegistry.get_instance("cache1") is second
        assert CacheBackendRegistry.get_instance("framework:cache1") is first
        # 切换到 user 实现（目标为 user:cache1）
        CacheBackendRegistry.activate("cache1", "user:cache1")
        assert "cache1" in CacheBackendRegistry.active_names()
        assert CacheBackendRegistry.get_instance("cache1") is second
        # 切换到 framework 实现（可观察的运行时切换）
        CacheBackendRegistry.activate("cache1", "framework:cache1")
        assert CacheBackendRegistry.get_instance("cache1") is first
        # deactivate 恢复默认（user 优先 → second）
        CacheBackendRegistry.deactivate("cache1")
        assert CacheBackendRegistry.active_names() == []
        assert CacheBackendRegistry.get_instance("cache1") is second
    finally:
        CacheBackendRegistry.deactivate("cache1")
        CacheBackendRegistry.unregister_instance("cache1")


def test_ref_unregistered_raises_config_error():
    """app.cache.type=ref:nope 未注册实例：create_app 快速失败（ConfigError）"""
    with pytest.raises(ConfigError, match="ref:nope"):
        create_app({"app.cache.type": "ref:nope"})


def test_fallback_returns_memory_when_primary_missing():
    """fallback：主策略未注册（get 抛 KeyError）回退 memory 工厂，正常返回 MemoryCacheBackend"""
    settings = Settings(DictConfigSource({"app.cache.max_size": 11}))
    factory = CacheBackendRegistry.fallback("missing_primary", "memory")
    backend = factory(settings)
    assert isinstance(backend, MemoryCacheBackend)
    assert backend.config.max_size == 11
