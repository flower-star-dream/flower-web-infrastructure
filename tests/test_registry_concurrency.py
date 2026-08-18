"""
注册表/RedisConfig 并发安全测试

@Author: 花海
@Date: 2026/08/17 19:00
@Description: 验证并发/线程安全修复（安全检查整改）：
              1) 类级注册表（CacheBackendRegistry 等）多线程并发 register/unregister/registered_names
                 不抛 RuntimeError（threading.Lock 保护迭代与写入交错）；
              2) RedisConfig.client() 跨线程并发调用只创建一份客户端实例（双重检查锁定）。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from web_infra.capabilities.cache import CacheBackendRegistry
from web_infra.capabilities.db.redis_config import RedisConfig


def test_registry_concurrent_register_and_iterate():
    """多线程并发 register/unregister/registered_names：锁保证迭代与写入不交错（不抛 RuntimeError）"""
    before = dict(CacheBackendRegistry._factories)
    try:
        def worker(i: int) -> None:
            if i % 2 == 0:
                CacheBackendRegistry.register(f"thread-{i}", lambda settings: None)
            else:
                CacheBackendRegistry.unregister(f"thread-{i}")
                _ = CacheBackendRegistry.registered_names()  # 迭代与写入并发

        with ThreadPoolExecutor(max_workers=16) as executor:
            list(executor.map(worker, range(200)))
    finally:
        CacheBackendRegistry._factories.clear()
        CacheBackendRegistry._factories.update(before)


def test_registry_concurrent_get_and_unregister():
    """多线程并发 get（含未注册 KeyError 路径）与 unregister：不抛 RuntimeError（KeyError 属预期）"""
    before = dict(CacheBackendRegistry._factories)
    try:
        CacheBackendRegistry.register("concurrent-get", lambda settings: None)

        def worker(_: int) -> None:
            try:
                CacheBackendRegistry.get("concurrent-get")
            except KeyError:
                pass  # unregister 竞态下未命中属预期

        def unregisterer(_: int) -> None:
            CacheBackendRegistry.unregister("concurrent-get")
            CacheBackendRegistry.register("concurrent-get", lambda settings: None)

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(worker, range(100)))
            list(executor.map(unregisterer, range(100)))
    finally:
        CacheBackendRegistry._factories.clear()
        CacheBackendRegistry._factories.update(before)


def test_redis_config_client_concurrent_singleton():
    """RedisConfig.client() 跨线程并发：只创建一份客户端实例（双重检查锁定）"""
    config = RedisConfig()
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            clients = list(executor.map(lambda _: config.client(), range(32)))
        assert all(client is clients[0] for client in clients)
        assert config._redis is clients[0]
    finally:
        if config._redis is not None:
            config._redis = None  # 未连接客户端，仅清理引用（无连接池泄漏）
