"""
Nacos 配置属性

@Author: 花海
@Date: 2026/08/14 10:00
@Description: Nacos 注册中心/配置中心的统一配置属性，字段与官方 nacos-sdk-python v2
              客户端配置（ClientConfig）对齐，供注册中心与配置中心共用。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class NacosProperties(BaseModel):
    """Nacos 配置属性（服务发现 + 配置中心共用）"""

    server_addresses: str = Field(default="localhost:8848", description="Nacos 服务地址（多个地址用逗号分隔）")
    namespace: str = Field(default="public", description="命名空间")
    group: str = Field(default="DEFAULT_GROUP", description="分组")
    data_id: str = Field(default="", description="配置 dataId")
    username: str = Field(default="", description="用户名")
    password: str = Field(default="", description="密码")
    access_key: str = Field(default="", description="阿里云 AccessKey（AK/SK 认证，可选）")
    secret_key: str = Field(default="", description="阿里云 SecretKey（AK/SK 认证，可选）")
    log_level: str = Field(default="INFO", description="SDK 日志级别")
    grpc_timeout_ms: int = Field(default=5000, description="gRPC 请求超时（毫秒）")
    tls_enabled: bool = Field(default=False, description="是否启用 TLS")
    tls_ca_file: str = Field(default="", description="CA 证书文件路径")
    tls_cert_file: str = Field(default="", description="客户端证书文件路径")
    tls_key_file: str = Field(default="", description="客户端私钥文件路径")
    register_enabled: bool = Field(default=False, description="是否启用服务注册")
    config_enabled: bool = Field(default=False, description="是否启用配置中心")
    heartbeat_interval: int = Field(default=5, description="心跳间隔（秒），映射 SDK 毫秒配置（临时实例自动心跳保活）")
    register_ip: str = Field(
        default="",
        description="注册到注册中心的对外 IP；容器/多网卡场景下自动探测到的通常是容器内部 IP（外部不可达），"
                    "应显式配置宿主机 IP 或 Pod IP（留空时自动探测：NACOS_REGISTER_IP > POD_IP > HOST_IP > 默认网关 > 本机探测）",
    )
