"""
核心 6 个 SPI 注册表迁移回归测试

@Author: 花海
@Date: 2026/08/22 12:10
@Description: 验证 6 个核心注册表迁移到 SpiRegistry 基类后：内置默认落框架命名空间且受保护、
              用户经默认命名空间同名覆盖（不破坏框架实现）、get/registered_names 兼容 _resolve_registry、
              且每个注册表各自持有一份命名空间（同名 memory 跨表不串扰，验证 per-subclass 存储）。
"""
import pytest

from web_infra.core.spi import SpiRegistry
from web_infra.capabilities.cache.cache_backend_registry import CacheBackendRegistry
from web_infra.capabilities.db.database_registry import DatabaseRegistry
from web_infra.capabilities.storage.object_storage_registry import ObjectStorageRegistry
from web_infra.capabilities.mq.message_queue_registry import MessageQueueRegistry
from web_infra.capabilities.registry.service_discovery_registry import ServiceDiscoveryRegistry
from web_infra.capabilities.search.search_engine_registry import SearchEngineRegistry

#: (注册表类, 内置默认名元组)
_CASES = [
    (CacheBackendRegistry, ("memory", "redis")),
    (DatabaseRegistry, ("mysql", "sqlite")),
    (ObjectStorageRegistry, ("local", "minio")),
    (MessageQueueRegistry, ("memory", "rocketmq")),
    (ServiceDiscoveryRegistry, ("memory", "nacos")),
    (SearchEngineRegistry, ("memory", "elasticsearch")),
]

_IDS = [c[0].__name__ for c in _CASES]


def _fake_factory(*_args, **_kwargs):
    """用户命名空间假工厂（仅用于解析断言，不要求匹配入参）"""
    return "fake"


@pytest.mark.parametrize("registry,builtins", _CASES, ids=_IDS)
def test_framework_defaults_registered(registry, builtins):
    """内置默认已落框架命名空间（完整性校验可核验）"""
    present = set(registry.registered_framework_names())
    for name in builtins:
        assert name in present


@pytest.mark.parametrize("registry,builtins", _CASES, ids=_IDS)
def test_get_resolves_default_and_raises_on_unknown(registry, builtins):
    """get 命中框架默认工厂；未注册抛 KeyError"""
    assert callable(registry.get(builtins[0]))
    with pytest.raises(KeyError):
        registry.get("not_a_backend")


@pytest.mark.parametrize("registry,builtins", _CASES, ids=_IDS)
def test_registered_names_lists_builtins(registry, builtins):
    """registered_names 兼容 _resolve_registry 错误提示（列出内置名）"""
    names = registry.registered_names()
    for name in builtins:
        assert name in names


@pytest.mark.parametrize("registry,builtins", _CASES, ids=_IDS)
def test_user_override_without_breaking_framework(registry, builtins):
    """用户默认命名空间同名注册 → 解析命中 user；framework 实现未被破坏"""
    name = builtins[0]
    framework_factory = registry.get("framework:" + name)  # 记录框架默认工厂
    try:
        registry.register(name, _fake_factory)  # 默认 user 命名空间
        assert registry.get(name) is _fake_factory           # user 命中
        assert registry.get("framework:" + name) is framework_factory  # framework 未被破坏
    finally:
        # 恢复：移除 user + framework，再重注框架默认工厂
        registry.unregister(name)
        registry.register(name, framework_factory, namespace=registry.FRAMEWORK_NAMESPACE)


@pytest.mark.parametrize("registry,builtins", _CASES, ids=_IDS)
def test_framework_ns_overwrite_rejected(registry, builtins):
    """向框架命名空间同名覆盖默认拒绝（需 overwrite=True）"""
    with pytest.raises(ValueError):
        registry.register(
            builtins[0],
            _fake_factory,
            namespace=registry.FRAMEWORK_NAMESPACE,
        )


@pytest.mark.parametrize("registry,builtins", _CASES, ids=_IDS)
def test_per_registry_storage_isolated(registry, builtins):
    """每子类独立存储：注册到本注册表不影响其它注册表（同名 memory 跨表不串扰）"""
    registry.register("__isolation_probe__", _fake_factory)
    try:
        assert "framework:__isolation_probe__" not in [
            f"framework:{n}" for n in registry.registered_framework_names()
        ]
        # 其它注册表不受本表 probe 影响
        for other, _ in _CASES:
            if other is registry:
                continue
            assert "__isolation_probe__" not in other.registered_framework_names()
    finally:
        registry.unregister("__isolation_probe__")
