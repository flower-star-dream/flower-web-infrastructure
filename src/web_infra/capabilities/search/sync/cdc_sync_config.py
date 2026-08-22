"""
CDC 同步配置

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 搜索引擎同步配置模型（app.search.sync，搜索引擎数据同步方案 §8）：开关、类型
              （cdc/dual_write/custom）、数据源/目标/位点存储类型、MySQL binlog 连接参数、
              重试策略、删除策略、双写、空闲对账与表映射。敏感配置经环境变量注入
              （$APP_SEARCH_SYNC_* 占位，见 application.default.yml / 脚手架 .env.example）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from web_infra.infra.config.settings import Settings
from web_infra.capabilities.search.sync.search_sync_constant import SearchSyncConstant


class MysqlCdcConfig(BaseModel):
    """MySQL binlog 连接配置（app.search.sync.cdc.mysql）"""

    host: str = Field(default="127.0.0.1", description="MySQL 主机（缺省复用 app.db.mysql 连接参数）")
    port: int = Field(default=3306, description="MySQL 端口")
    username: str = Field(default="", description="复制账号（需 REPLICATION SLAVE/CLIENT 权限）")
    password: str = Field(default="", description="复制账号密码（经环境变量注入）")
    database: str = Field(default="", description="监听库（空 = 全部库）")
    server_id: int = Field(default=10001, description="伪从库 server-id（多实例必须唯一）")
    tables: list[str] = Field(default_factory=list, description="表监听白名单（空 = 全部）")
    bulk_size: int = Field(default=500, ge=1, le=SearchSyncConstant.MAX_BULK_SIZE, description="批量攒批条数")
    flush_interval_seconds: float = Field(default=1.0, ge=0.0, description="批量最大等待（秒）")
    heartbeat_interval_seconds: int = Field(default=30, ge=1, description="心跳间隔（秒，防连接超时断开）")


class SearchSyncRetryConfig(BaseModel):
    """同步目标写入重试策略（app.search.sync.cdc.retry）"""

    max_attempts: int = Field(default=5, ge=1, description="目标写入失败最大重试次数")
    backoff_base_seconds: float = Field(default=1.0, ge=0.0, description="指数退避基数（秒）")
    max_backoff_seconds: float = Field(default=60.0, ge=1.0, description="最大退避（秒）")


class DualWriteConfig(BaseModel):
    """双写同步配置（app.search.sync.dual_write）"""

    topic: str = Field(default=SearchSyncConstant.SYNC_TOPIC, description="双写同步 Topic")
    event_type: str = Field(default=SearchSyncConstant.OUTBOX_EVENT_TYPE, description="Outbox 事件类型标记")


class ReconcileConfig(BaseModel):
    """空闲时段全量对账配置（app.search.sync.reconcile，搜索引擎数据同步方案 §9）"""

    enabled: bool = Field(default=True, description="是否启用空闲对账兜底")
    mode: Literal["reconcile", "rebuild"] = Field(default="reconcile", description="reconcile 差异对账 / rebuild 重建+alias 切换")
    cron: str = Field(default="0 3 * * *", description="定时表达式（框架 schedule）")
    window: list[int] = Field(default=[2, 6], description="空闲窗口（小时，窗口外触发跳过本周期）")
    batch_size: int = Field(default=1000, ge=1, le=SearchSyncConstant.MAX_BULK_SIZE, description="对账/重建分批条数")
    tables: list[str] = Field(default_factory=list, description="对账表（空 = 复用 cdc 表映射/全量）")


class CdcSyncConfig(BaseModel):
    """搜索引擎同步模块配置（app.search.sync）"""

    enabled: bool = Field(default=False, description="是否启用同步（默认关闭，与 search 组件一致）")
    type: Literal["cdc", "dual_write", "custom"] = Field(
        default="cdc", description="同步类型：cdc（默认）/ dual_write / custom（自定义 SPI）"
    )
    source: str = Field(default="mysql", description="数据源：mysql（默认）/ 自定义注册表名")
    target: str = Field(default="es", description="目标：es（默认）/ 自定义注册表名")
    offset_store: Literal["redis", "file", "mysql"] = Field(
        default="redis", description="位点存储：redis（默认）/ file / mysql"
    )
    cdc: MysqlCdcConfig = Field(default_factory=MysqlCdcConfig, description="MySQL binlog CDC 配置")
    retry: SearchSyncRetryConfig = Field(default_factory=SearchSyncRetryConfig, description="写入重试策略")
    delete_strategy: Literal["soft", "hard"] = Field(default="soft", description="删除策略：soft 软删标记 / hard 物理删除")
    dual_write: DualWriteConfig = Field(default_factory=DualWriteConfig, description="双写配置")
    reconcile: ReconcileConfig = Field(default_factory=ReconcileConfig, description="空闲对账配置")
    mapping: dict[str, dict] = Field(default_factory=dict, description="表 → 索引映射（见设计 §5.4）")

    @model_validator(mode="after")
    def _validate_window(self) -> "CdcSyncConfig":
        """校验空闲窗口合法（start < end 且 0~23）"""
        window = self.reconcile.window
        if len(window) == 2:
            if not (0 <= window[0] < window[1] <= 24):
                raise ValueError("reconcile.window 须满足 0 <= start < end <= 24")
        return self

    @classmethod
    def from_settings(cls, settings: Settings) -> "CdcSyncConfig":
        """从统一配置读取 app.search.sync 装配（缺省回落默认值）"""
        data = settings.get("app.search.sync") or {}
        return cls.model_validate(data)
