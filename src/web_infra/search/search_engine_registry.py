"""
搜索引擎注册表

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 搜索引擎 SPI 注册表：按 type 名注册/查询 SearchEngineInterface 工厂，
              装配期（app.search.type）按名实例化；内置 memory/elasticsearch 条目，
              用户自定义搜索引擎（自研/第三方）经 register 注册后即可接入，
              无需改动框架装配代码；未注册的 type 装配期快速失败（ConfigError）。
              elasticsearch 条目仅在工厂被调用（实例化）时才加载 es extra 依赖，
              未安装 es extra 时 memory 装配不受影响。
"""
from __future__ import annotations

from threading import Lock
from typing import Callable, ClassVar

from web_infra.config import Settings
from web_infra.search.search_engine_interface import SearchEngineInterface

#: 搜索引擎工厂签名：入参装配配置（Settings），返回搜索引擎实现
SearchEngineFactory = Callable[[Settings], SearchEngineInterface]


class SearchEngineRegistry:
    """搜索引擎注册表（类级注册，全局装配；同名覆盖）"""

    _factories: ClassVar[dict[str, SearchEngineFactory]] = {}
    _lock = Lock()

    @classmethod
    def register(cls, name: str, factory: SearchEngineFactory) -> None:
        """注册搜索引擎工厂（同名覆盖）。

        :param name: type 名（与 yml app.search.type 匹配）
        :param factory: 工厂，入参 Settings，返回 SearchEngineInterface 实现
        """
        with cls._lock:
            cls._factories[name] = factory

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销后端（不存在时静默）"""
        with cls._lock:
            cls._factories.pop(name, None)

    @classmethod
    def get(cls, name: str) -> SearchEngineFactory:
        """按名查询工厂；未注册抛 KeyError（装配期由调用方捕获转 ConfigError）"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory

    @classmethod
    def create(cls, name: str, settings: Settings) -> SearchEngineInterface:
        """按名实例化搜索引擎；未注册抛 KeyError"""
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


def _memory_search_factory(settings: Settings) -> SearchEngineInterface:
    """内置 memory：内存搜索引擎（单实例/测试场景，无外部依赖）"""
    from web_infra.search.in_memory_search_engine import InMemorySearchEngine

    return InMemorySearchEngine()


def _elasticsearch_search_factory(settings: Settings) -> SearchEngineInterface:
    """内置 elasticsearch：ES 生产实现（elasticsearch-dsl；连接参数来自 app.search 配置）"""
    from web_infra.search.elasticsearch_search_engine import ElasticsearchSearchEngine
    from web_infra.search.search_config import SearchConfig

    config = SearchConfig.from_settings(settings)
    es_config = config.elasticsearch
    return ElasticsearchSearchEngine(
        hosts=es_config.resolve_hosts(),
        index_prefix=config.index_prefix,
        username=es_config.username,
        password=es_config.password,
        verify_certs=es_config.verify_certs,
        connect_timeout=es_config.connect_timeout,
        read_timeout=es_config.read_timeout,
    )


# 内置后端条目（模块导入即注册，幂等）
SearchEngineRegistry.register("memory", _memory_search_factory)
SearchEngineRegistry.register("elasticsearch", _elasticsearch_search_factory)
