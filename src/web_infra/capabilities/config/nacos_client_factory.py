"""
Nacos 客户端配置构建函数

@Author: 花海
@Date: 2026/08/15 15:00
@Description: 将应用侧 NacosProperties 映射为 nacos-sdk-python v2 的 ClientConfig，
              注册中心与配置中心共用，避免两处重复实现 SDK 配置拼装。
              延迟导入 SDK：最小安装（不含 nacos extras）时，仅在实际使用 Nacos 组件时才会报缺少依赖。
"""
from __future__ import annotations

from web_infra.capabilities.config.nacos_properties import NacosProperties


def build_client_config(properties: NacosProperties):
    """构建 nacos-sdk-python 客户端配置（ClientConfig）。

    映射关系：
    - server_addresses -> server_address（支持逗号分隔多地址）
    - namespace -> namespace_id
    - username/password -> 账号密码认证
    - access_key/secret_key -> 阿里云 AK/SK 认证
    - heartbeat_interval -> heart_beat_interval（秒转毫秒，临时实例自动心跳保活）
    - grpc_timeout_ms -> GRPCConfig.grpc_timeout
    - tls_enabled 等 -> TLSConfig
    """
    from v2.nacos import ClientConfigBuilder, GRPCConfig, TLSConfig

    builder = ClientConfigBuilder()
    builder.server_address(properties.server_addresses)
    builder.namespace_id(properties.namespace)
    builder.username(properties.username)
    builder.password(properties.password)
    builder.log_level(properties.log_level)
    builder.heart_beat_interval(properties.heartbeat_interval * 1000)
    builder.grpc_config(GRPCConfig(grpc_timeout=properties.grpc_timeout_ms))
    if properties.access_key:
        builder.access_key(properties.access_key)
    if properties.secret_key:
        builder.secret_key(properties.secret_key)
    if properties.tls_enabled:
        builder.tls_config(
            TLSConfig(
                enabled=True,
                ca_file=properties.tls_ca_file,
                cert_file=properties.tls_cert_file,
                key_file=properties.tls_key_file,
            )
        )
    return builder.build()
