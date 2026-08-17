"""
缓存模块

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 缓存 Key 统一生成与缓存后端抽象聚合导出。
              - KeyBuilder：遵循规范 §5.6/§5.7（占位符模板 + 统一生成方法）
              - CacheBackendInterface / MemoryCacheBackend：遵循规范 §8/§16.5（缓存后端抽象 + 内存实现）
"""
from web_infra.cache.key_builder import KeyBuilder
from web_infra.cache.tenant_key_builder import TenantKeyBuilder
from web_infra.cache.cache_backend_interface import CacheBackendInterface
from web_infra.cache.cache_config import CacheConfig
from web_infra.cache.memory_cache_backend import MemoryCacheBackend
from web_infra.cache.cache_backend_registry import CacheBackendRegistry

__all__ = [
    "KeyBuilder", "TenantKeyBuilder", "CacheBackendInterface", "CacheConfig", "MemoryCacheBackend",
    "CacheBackendRegistry",
]
