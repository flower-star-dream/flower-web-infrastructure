"""
缓存后端注册表

@Author: 花海
@Date: 2026/08/17 17:00
@Description: 缓存后端 SPI 注册表：按 type 名注册/查询 CacheBackendInterface 工厂，
              装配期（app.cache.type）按名实例化；内置 memory/redis 条目，
              用户自定义缓存后端（第三方/自研）经 register 注册后即可接入 create_app，
              无需改动框架装配代码；未注册的 type 装配期快速失败（ConfigError）。
"""
from __future__ import annotations

from threading import Lock
from typing import Callable, ClassVar

from web_infra.capabilities.cache.cache_backend_interface import CacheBackendInterface
from web_infra.infra.config import Settings

#: 缓存后端工厂签名：入参装配配置（Settings），返回缓存后端实现
CacheBackendFactory = Callable[[Settings], CacheBackendInterface]

# Redis 连接配置字段（与 yml app.cache.redis 段对齐，缺省用 RedisConfig 默认值）
_REDIS_CONFIG_FIELDS = (
    "host", "port", "db", "password", "username", "max_connections",
    "decode_responses", "socket_connect_timeout", "socket_timeout",
    "socket_keepalive", "health_check_interval", "retry_on_timeout",
)


class CacheBackendRegistry:
    """缓存后端注册表（类级注册，全局装配；同名覆盖）"""

    _factories: ClassVar[dict[str, CacheBackendFactory]] = {}
    _lock = Lock()

    @classmethod
    def register(cls, name: str, factory: CacheBackendFactory) -> None:
        """注册缓存后端工厂（同名覆盖）。

        :param name: type 名（与 yml app.cache.type 匹配）
        :param factory: 工厂，入参 Settings，返回 CacheBackendInterface 实现
        """
        with cls._lock:
            cls._factories[name] = factory

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销后端（不存在时静默）"""
        with cls._lock:
            cls._factories.pop(name, None)

    @classmethod
    def get(cls, name: str) -> CacheBackendFactory:
        """按名查询工厂；未注册抛 KeyError（装配期由 create_app 捕获转 ConfigError）"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory

    @classmethod
    def create(cls, name: str, settings: Settings) -> CacheBackendInterface:
        """按名实例化缓存后端；未注册抛 KeyError"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory(settings)

    @classmethod
    def registered_names(cls) -> list[str]:
        """已注册后端名清单"""
        with cls._lock:
            return list(cls._factories)


def _memory_cache_factory(settings: Settings) -> CacheBackendInterface:
    """内置 memory：内存缓存后端（单实例）"""
    from web_infra.capabilities.cache.cache_config import CacheConfig
    from web_infra.capabilities.cache.memory_cache_backend import MemoryCacheBackend

    return MemoryCacheBackend(CacheConfig(max_size=settings.get_int("app.cache.max_size")))


def _redis_cache_factory(settings: Settings) -> CacheBackendInterface:
    """内置 redis：Redis 缓存后端（复用框架 Redis 连接配置，JWT Token 状态存储默认跟随同一实例）"""
    from web_infra.capabilities.db.redis_cache_backend import RedisCacheBackend
    from web_infra.capabilities.db.redis_config import RedisConfig
    from web_infra.capabilities.security.jwt_util import JWTUtil

    config = RedisConfig(
        **{
            field: settings.get(f"app.cache.redis.{field}")
            for field in _REDIS_CONFIG_FIELDS
            if settings.get(f"app.cache.redis.{field}") is not None
        }
    )
    JWTUtil.set_redis_config(config)
    return RedisCacheBackend(config=config)


# 内置后端条目（模块导入即注册，幂等）
CacheBackendRegistry.register("memory", _memory_cache_factory)
CacheBackendRegistry.register("redis", _redis_cache_factory)
