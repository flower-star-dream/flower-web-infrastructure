"""
搜索引擎配置

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 搜索引擎模块配置模型（app.search）：开关、实现类型（memory/elasticsearch/custom）
              与 ES 连接参数（hosts/账号/证书校验/超时）。索引前缀用于真实索引命名隔离。
              敏感配置经环境变量注入（$APP_SEARCH_* 占位，见 application.default.yml）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from web_infra.config.settings import Settings
from web_infra.search.search_constant import SearchConstant


class ElasticsearchSearchConfig(BaseModel):
    """Elasticsearch 连接配置（app.search.elasticsearch）"""

    hosts: list[str] | str = Field(
        default=["http://localhost:9200"], description="ES 节点地址（列表或逗号分隔字符串，如 http://host:9200）"
    )
    username: str = Field(default="", description="ES 账号（空表示无需认证）")
    password: str = Field(default="", description="ES 密码（经环境变量注入）")
    verify_certs: bool = Field(default=True, description="TLS 证书校验（生产默认开启；测试环境可显式关闭）")
    connect_timeout: float = Field(default=5.0, description="连接超时（秒）")
    read_timeout: float = Field(default=30.0, description="读超时（秒）")

    def resolve_hosts(self) -> list[str]:
        """归一化 hosts：字符串按逗号切分，列表原样返回"""
        if isinstance(self.hosts, str):
            return [host.strip() for host in self.hosts.split(",") if host.strip()]
        return list(self.hosts)


class SearchConfig(BaseModel):
    """搜索引擎模块配置（app.search）"""

    enabled: bool = Field(default=False, description="是否启用（与缓存/存储组件一致，默认关闭）")
    type: Literal["memory", "elasticsearch", "custom"] = Field(
        default="memory", description="实现类型：memory（内存默认）/ elasticsearch（生产推荐）/ custom（自研，按 SPI 接入）"
    )
    index_prefix: str = Field(default=SearchConstant.DEFAULT_INDEX_PREFIX, description="索引名前缀（真实索引 {prefix}_{tenant}_{index}）")
    elasticsearch: ElasticsearchSearchConfig = Field(
        default_factory=ElasticsearchSearchConfig, description="ES 连接配置（type=elasticsearch 时生效）"
    )

    @classmethod
    def from_settings(cls, settings: Settings) -> "SearchConfig":
        """从统一配置读取 app.search 装配（缺省回落默认值）"""
        data = settings.get("app.search") or {}
        return cls.model_validate(data)
