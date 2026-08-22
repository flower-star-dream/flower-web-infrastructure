"""
SPI 启动完整性校验测试

@Author: 花海
@Date: 2026/08/22 12:20
@Description: 框架启动时校验核心 6 个注册表的框架默认实现存在；缺失抛 ConfigError 快速失败。
"""
import pytest

from web_infra import create_app
from web_infra.capabilities.cache.cache_backend_registry import CacheBackendRegistry
from web_infra.capabilities.db.database_registry import DatabaseRegistry
from web_infra.capabilities.storage.object_storage_registry import ObjectStorageRegistry
from web_infra.capabilities.mq.message_queue_registry import MessageQueueRegistry
from web_infra.capabilities.registry.service_discovery_registry import ServiceDiscoveryRegistry
from web_infra.capabilities.search.search_engine_registry import SearchEngineRegistry
from web_infra.infra.config.config_error import ConfigError

#: (注册表类, 用于完整性校验的关键框架默认名)
_CASES = [
    (CacheBackendRegistry, "memory"),
    (DatabaseRegistry, "mysql"),
    (ObjectStorageRegistry, "local"),
    (MessageQueueRegistry, "memory"),
    (ServiceDiscoveryRegistry, "memory"),
    (SearchEngineRegistry, "memory"),
]
_IDS = [f"{c[0].__name__}:{c[1]}" for c in _CASES]


@pytest.mark.parametrize("registry,name", _CASES, ids=_IDS)
def test_integrity_raises_when_framework_default_missing(registry, name):
    """移除某注册表的框架默认实现 → 启动 ConfigError 快速失败"""
    framework_factory = registry.get("framework:" + name)
    try:
        registry.unregister(name)
        with pytest.raises(ConfigError):
            create_app(settings={})
    finally:
        registry.register(name, framework_factory, namespace=registry.FRAMEWORK_NAMESPACE)


def test_integrity_ok_when_default_present():
    """所有核心框架默认存在时不抛错（正常启动）"""
    app = create_app(settings={})
    assert app is not None
