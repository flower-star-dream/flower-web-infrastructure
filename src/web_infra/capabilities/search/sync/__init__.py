"""
搜索引擎同步子包

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 搜索引擎数据同步模块聚合导出（搜索引擎数据同步方案）：统一变更事件模型、三个 SPI
              （数据源/目标/位点存储）、三种位点存储、ES 目标、编排管道、装配注册表、
              MySQL binlog 默认源（[cdc] extra 延迟导入）、双写、空闲对账、配置、常量、错误码与指标。
              模块导入即注册内置条目（位点存储 redis/file/mysql），无需用户手动注册。
"""
from web_infra.capabilities.search.sync.cdc_change_event import CdcChangeEvent, CdcOp
from web_infra.capabilities.search.sync.cdc_offset_store_interface import CdcOffsetStoreInterface
from web_infra.capabilities.search.sync.cdc_source_interface import CdcEventHandler, CdcSourceInterface
from web_infra.capabilities.search.sync.cdc_sync_pipeline import CdcSyncPipeline
from web_infra.capabilities.search.sync.cdc_sync_registry import (
    CdcOffsetStoreFactory,
    CdcSourceFactory,
    CdcSyncRegistry,
    CdcTargetFactory,
)
from web_infra.capabilities.search.sync.cdc_sync_target_interface import CdcSyncTargetInterface
from web_infra.capabilities.search.sync.cdc_sync_config import (
    CdcSyncConfig,
    MysqlCdcConfig,
    ReconcileConfig,
    SearchSyncRetryConfig,
)
from web_infra.capabilities.search.sync.dual_write_sync_service import (
    SearchSyncOutboxConsumer,
    SearchSyncOutboxWriter,
)
from web_infra.capabilities.search.sync.es_cdc_sync_target import EsCdcSyncTarget
from web_infra.capabilities.search.sync.file_offset_store import FileOffsetStore
from web_infra.capabilities.search.sync.full_reconcile_service import RowReader, FullReconcileService
from web_infra.capabilities.search.sync.mysql_binlog_cdc_source import MysqlBinlogCdcSource
from web_infra.capabilities.search.sync.mysql_offset_store import MysqlOffsetStore
from web_infra.capabilities.search.sync.redis_offset_store import RedisOffsetStore
from web_infra.capabilities.search.sync.search_sync_constant import SearchSyncConstant
from web_infra.capabilities.search.sync.search_sync_error_code import SearchSyncErrorCode, SearchSyncErrorCodeEnum
from web_infra.capabilities.search.sync.sync_metrics import SyncMetrics

__all__ = [
    # 事件模型
    "CdcChangeEvent", "CdcOp",
    # SPI
    "CdcSourceInterface", "CdcEventHandler", "CdcSyncTargetInterface", "CdcOffsetStoreInterface",
    # 位点存储
    "RedisOffsetStore", "FileOffsetStore", "MysqlOffsetStore",
    # 目标与管道
    "EsCdcSyncTarget", "CdcSyncPipeline",
    # 注册表与工厂
    "CdcSyncRegistry", "CdcSourceFactory", "CdcTargetFactory", "CdcOffsetStoreFactory",
    # 配置
    "CdcSyncConfig", "MysqlCdcConfig", "SearchSyncRetryConfig", "ReconcileConfig",
    # 双写与对账
    "SearchSyncOutboxWriter", "SearchSyncOutboxConsumer", "FullReconcileService", "RowReader",
    # MySQL 默认源
    "MysqlBinlogCdcSource",
    # 常量 / 错误码 / 指标
    "SearchSyncConstant", "SearchSyncErrorCode", "SearchSyncErrorCodeEnum", "SyncMetrics",
]

# 内置位点存储条目（模块导入即注册，幂等；工厂在实例化时读取配置并构造实现）
def _file_offset_factory(settings) -> FileOffsetStore:
    """内置 file：本地文件位点存储（单实例/测试场景，无外部依赖）"""
    return FileOffsetStore()


def _redis_offset_factory(settings) -> RedisOffsetStore:
    """内置 redis：Redis 位点存储（连接参数读 app.cache.redis，缺省 127.0.0.1:6379）"""
    from web_infra.capabilities.db import RedisConfig

    cache = (settings.get("app.cache.redis") or {}) if settings else {}
    config = RedisConfig(
        host=cache.get("host", "localhost"),
        port=int(cache.get("port", 6379)),
        db=int(cache.get("db", 0)),
        password=cache.get("password"),
        username=cache.get("username"),
    )
    return RedisOffsetStore(config.client())


CdcSyncRegistry.register_offset_store("redis", _redis_offset_factory)
CdcSyncRegistry.register_offset_store("file", _file_offset_factory)
