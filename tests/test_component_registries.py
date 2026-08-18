"""
组件 SPI 注册表测试（缓存/对象存储/消息队列/服务注册发现）

@Author: 花海
@Date: 2026/08/17 17:30
@Description: 验证四组件注册表（CacheBackendRegistry/ObjectStorageRegistry/MessageQueueRegistry/
              ServiceDiscoveryRegistry）：
              1) 类级注册表基础语义：内置条目、注册/查询/实例化/注销/同名覆盖；
              2) create_app 装配：app.*.type 命中注册表按名装配（内置默认 + 自定义注册接入）；
              3) 未注册的 type 启动期快速失败（ConfigError，避免静默回落默认实现掩盖配置错误）。
"""
from __future__ import annotations

import pytest

from web_infra.core.application import create_app
from web_infra.capabilities.cache import CacheBackendRegistry, CacheConfig, MemoryCacheBackend
from web_infra.infra.config import ConfigError
from web_infra.capabilities.mq import InMemoryMessageQueue, MessageQueueRegistry
from web_infra.capabilities.registry import InMemoryServiceRegistry, ServiceDiscoveryRegistry
from web_infra.capabilities.storage import LocalObjectStorage, ObjectStorageRegistry, StorageConfig


@pytest.fixture
def clean_registries():
    """测试后清理四个全局注册表（保留内置条目）"""
    registries = (
        CacheBackendRegistry,
        ObjectStorageRegistry,
        MessageQueueRegistry,
        ServiceDiscoveryRegistry,
    )
    before = [dict(r._factories) for r in registries]
    yield
    for registry, snapshot in zip(registries, before):
        registry._factories.clear()
        registry._factories.update(snapshot)


# ------------------------------------------------------------------
# 注册表基础语义
# ------------------------------------------------------------------


def test_builtin_entries_registered(clean_registries):
    """四注册表内置条目导入即注册"""
    assert set(CacheBackendRegistry.registered_names()) == {"memory", "redis"}
    assert set(ObjectStorageRegistry.registered_names()) == {"local", "minio"}
    assert set(MessageQueueRegistry.registered_names()) == {"memory", "rocketmq"}
    assert set(ServiceDiscoveryRegistry.registered_names()) == {"memory", "nacos"}


def test_register_overwrite_and_unregister(clean_registries):
    """同名覆盖 + 注销（不存在时静默），未注册 get 抛 KeyError"""
    CacheBackendRegistry.register("custom", lambda s: MemoryCacheBackend(CacheConfig(max_size=1)))
    CacheBackendRegistry.register("custom", lambda s: MemoryCacheBackend(CacheConfig(max_size=2)))
    store = CacheBackendRegistry.create("custom", None)  # 工厂忽略 settings
    assert store.config.max_size == 2

    CacheBackendRegistry.unregister("custom")
    CacheBackendRegistry.unregister("custom")  # 重复注销静默
    with pytest.raises(KeyError):
        CacheBackendRegistry.get("custom")


# ------------------------------------------------------------------
# create_app 装配：自定义类型 + 未知类型
# ------------------------------------------------------------------

_CUSTOM_CACHE = "custom-cache"
_CUSTOM_STORAGE = "custom-storage"
_CUSTOM_MQ = "custom-mq"
_CUSTOM_REGISTRY = "custom-registry"


def _install_custom_factories() -> None:
    """注册四个自定义后端工厂（工厂入参 Settings 被忽略，便于断言装配链路）"""
    CacheBackendRegistry.register(_CUSTOM_CACHE, lambda s: MemoryCacheBackend(CacheConfig(max_size=321)))
    ObjectStorageRegistry.register(_CUSTOM_STORAGE, lambda s: LocalObjectStorage(StorageConfig(base_dir="custom")))
    MessageQueueRegistry.register(_CUSTOM_MQ, lambda s: InMemoryMessageQueue())
    ServiceDiscoveryRegistry.register(_CUSTOM_REGISTRY, lambda s: InMemoryServiceRegistry(instance_expire_seconds=30))


@pytest.mark.parametrize(
    ("registry", "type_value", "expected_type"),
    [
        (CacheBackendRegistry, _CUSTOM_CACHE, MemoryCacheBackend),
        (ObjectStorageRegistry, _CUSTOM_STORAGE, LocalObjectStorage),
        (MessageQueueRegistry, _CUSTOM_MQ, InMemoryMessageQueue),
        (ServiceDiscoveryRegistry, _CUSTOM_REGISTRY, InMemoryServiceRegistry),
    ],
)
def test_custom_type_assembles(clean_registries, registry, type_value, expected_type):
    """自定义后端经注册表注册后按 type 装配进 app.state（无需改动框架装配代码）"""
    _install_custom_factories()
    key = {
        CacheBackendRegistry: "app.cache.type",
        ObjectStorageRegistry: "app.storage.type",
        MessageQueueRegistry: "app.mq.type",
        ServiceDiscoveryRegistry: "app.registry.type",
    }[registry]
    app = create_app({key: type_value})
    component = app.state.components[{"app.cache.type": "cache", "app.storage.type": "storage",
                                      "app.mq.type": "mq", "app.registry.type": "registry"}[key]]
    assert isinstance(component, expected_type)


@pytest.mark.parametrize(
    "key",
    ["app.cache.type", "app.storage.type", "app.mq.type", "app.registry.type"],
)
def test_unknown_type_raises_config_error(clean_registries, key):
    """未注册的 type 启动期快速失败（ConfigError，避免静默回落默认实现）"""
    with pytest.raises(ConfigError, match="not-exist"):
        create_app({key: "not-exist"})


def test_default_components_assembled(clean_registries):
    """默认配置（内置默认 type）正常装配，行为与改造前一致"""
    app = create_app({"app.name": "default-components"})
    assert isinstance(app.state.cache, MemoryCacheBackend)
    assert isinstance(app.state.storage, LocalObjectStorage)
    assert isinstance(app.state.mq, InMemoryMessageQueue)
    assert isinstance(app.state.registry, InMemoryServiceRegistry)
