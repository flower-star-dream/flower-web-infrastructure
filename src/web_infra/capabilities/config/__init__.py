"""Nacos 配置中心接入（能力层）

@Author: 花海
@Date: 2026/08/18 17:00
@Description: Nacos 配置中心客户端与配置源（ConfigClientInterface SPI + nacos-sdk-python v2 实现）。
              本地配置读取（Settings/ConfigSource 等）位于 web_infra.infra.config（技术底座，被所有能力共用），
              此处仅含外部中间件（Nacos）接入的配置中心能力，随能力层按需引入（配置中心：第三方外部服务接入=能力）。
"""
from web_infra.capabilities.config.config_client_interface import ConfigClientInterface
from web_infra.capabilities.config.nacos_config_client import NacosConfigClient
from web_infra.capabilities.config.nacos_config_loader import NacosConfigLoader
from web_infra.capabilities.config.nacos_properties import NacosProperties

__all__ = [
    "ConfigClientInterface",
    "NacosConfigClient",
    "NacosConfigLoader",
    "NacosProperties",
]
