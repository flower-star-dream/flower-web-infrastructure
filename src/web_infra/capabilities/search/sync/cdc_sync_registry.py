"""
CDC 同步装配注册表

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 同步装配注册表（搜索引擎数据同步方案 §4.6）：按 type 名装配数据源/目标/位点存储
              工厂，内置条目模块导入即注册（幂等），register 同名覆盖，未注册抛 KeyError
              （装配期由调用方捕获转 ConfigError）。自定义实现经 register_* 即接入，无需改框架装配代码。
"""
from __future__ import annotations

from threading import Lock
from typing import Callable, ClassVar

from web_infra.capabilities.search.sync.cdc_offset_store_interface import CdcOffsetStoreInterface
from web_infra.capabilities.search.sync.cdc_source_interface import CdcSourceInterface
from web_infra.capabilities.search.sync.cdc_sync_target_interface import CdcSyncTargetInterface
from web_infra.infra.config import Settings

#: 数据源工厂签名：入参装配配置（Settings），返回 CdcSourceInterface 实现
CdcSourceFactory = Callable[[Settings], CdcSourceInterface]
#: 目标工厂签名：入参装配配置（Settings），返回 CdcSyncTargetInterface 实现
CdcTargetFactory = Callable[[Settings], CdcSyncTargetInterface]
#: 位点存储工厂签名：入参装配配置（Settings），返回 CdcOffsetStoreInterface 实现
CdcOffsetStoreFactory = Callable[[Settings], CdcOffsetStoreInterface]


class CdcSyncRegistry:
    """同步装配注册表（数据源/目标/位点存储，同名覆盖）"""

    _sources: ClassVar[dict[str, CdcSourceFactory]] = {}
    _targets: ClassVar[dict[str, CdcTargetFactory]] = {}
    _offset_stores: ClassVar[dict[str, CdcOffsetStoreFactory]] = {}
    _lock = Lock()

    # ------------------------------------------------------------------
    # 数据源
    # ------------------------------------------------------------------

    @classmethod
    def register_source(cls, name: str, factory: CdcSourceFactory) -> None:
        """注册数据源工厂（同名覆盖）。

        :param name: type 名（与 yml app.search.sync.source 匹配）
        :param factory: 工厂，入参 Settings，返回 CdcSourceInterface 实现
        """
        with cls._lock:
            cls._sources[name] = factory

    @classmethod
    def get_source(cls, name: str) -> CdcSourceFactory:
        """按名查询数据源工厂；未注册抛 KeyError"""
        with cls._lock:
            factory = cls._sources.get(name)
        if factory is None:
            raise KeyError(name)
        return factory

    @classmethod
    def registered_sources(cls) -> list[str]:
        """已注册数据源名清单"""
        with cls._lock:
            return list(cls._sources)

    # ------------------------------------------------------------------
    # 目标
    # ------------------------------------------------------------------

    @classmethod
    def register_target(cls, name: str, factory: CdcTargetFactory) -> None:
        """注册目标工厂（同名覆盖）。

        :param name: type 名（与 yml app.search.sync.target 匹配）
        :param factory: 工厂，入参 Settings，返回 CdcSyncTargetInterface 实现
        """
        with cls._lock:
            cls._targets[name] = factory

    @classmethod
    def get_target(cls, name: str) -> CdcTargetFactory:
        """按名查询目标工厂；未注册抛 KeyError"""
        with cls._lock:
            factory = cls._targets.get(name)
        if factory is None:
            raise KeyError(name)
        return factory

    @classmethod
    def registered_targets(cls) -> list[str]:
        """已注册目标名清单"""
        with cls._lock:
            return list(cls._targets)

    # ------------------------------------------------------------------
    # 位点存储
    # ------------------------------------------------------------------

    @classmethod
    def register_offset_store(cls, name: str, factory: CdcOffsetStoreFactory) -> None:
        """注册位点存储工厂（同名覆盖）。

        :param name: type 名（与 yml app.search.sync.offset_store 匹配）
        :param factory: 工厂，入参 Settings，返回 CdcOffsetStoreInterface 实现
        """
        with cls._lock:
            cls._offset_stores[name] = factory

    @classmethod
    def get_offset_store(cls, name: str) -> CdcOffsetStoreFactory:
        """按名查询位点存储工厂；未注册抛 KeyError"""
        with cls._lock:
            factory = cls._offset_stores.get(name)
        if factory is None:
            raise KeyError(name)
        return factory

    @classmethod
    def registered_offset_stores(cls) -> list[str]:
        """已注册位点存储名清单"""
        with cls._lock:
            return list(cls._offset_stores)
