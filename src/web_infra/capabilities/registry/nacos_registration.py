"""
Nacos 服务注册工具

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 封装服务注册/注销流程，自动获取本机 IP，简化使用。
"""
from __future__ import annotations

import os
import socket

from web_infra.capabilities.config.nacos_properties import NacosProperties
from web_infra.infra.constants.infra_constant import InfraConstant
from web_infra.capabilities.registry.nacos_discovery import NacosDiscoveryClient
from web_infra.capabilities.registry.service_instance import ServiceInstance


class NacosRegistration:
    """Nacos 服务注册工具类"""

    def __init__(self, properties: NacosProperties) -> None:
        self.properties = properties
        self.discovery_client = NacosDiscoveryClient(properties)
        self._service_name: str = ""
        self._instance: ServiceInstance | None = None

    async def register(
        self,
        service_name: str,
        port: int,
        ip: str | None = None,
        weight: float = 1.0,
        metadata: dict | None = None,
    ) -> bool:
        """注册当前服务到 Nacos"""
        self._service_name = service_name
        if not ip:
            ip = self._get_local_ip()
        self._instance = ServiceInstance(ip=ip, port=port, weight=weight, metadata=metadata or {})
        return await self.discovery_client.register(service_name, self._instance)

    async def deregister(self) -> bool:
        """注销当前服务"""
        if not self._service_name or not self._instance:
            return False
        return await self.discovery_client.deregister(self._service_name, self._instance)

    def _get_local_ip(self) -> str:
        """获取注册到注册中心的对外 IP（分级探测，容器场景兼容）。

        优先级从高到低：
        1. 配置显式指定（application.yml: app.registry.nacos.register_ip）
        2. 环境变量 NACOS_REGISTER_IP（通用，保持兼容）
        3. 环境变量 POD_IP（K8s 自动注入，集群内跨节点可达）
        4. 环境变量 HOST_IP（Docker 宿主机 IP，运维注入，外部设备可达）
        5. 默认网关 IP（容器 bridge 网络下为宿主机地址，注册中心在宿主机/同宿容器时可达）
        6. 本机 UDP 探测（裸机场景）
        7. 回环地址（兜底）

        容器场景下 UDP 探测拿到的通常是容器内部 IP（如 172.17.0.x），注册中心与其他服务
        不在同一设备时外部不可达，因此优先采用显式配置或平台注入的对外 IP。
        """
        # 1. 配置显式指定（最高优先级）
        if self.properties.register_ip:
            return self.properties.register_ip
        # 2. 通用环境变量（保持向后兼容）
        env_ip = os.environ.get("NACOS_REGISTER_IP")
        if env_ip:
            return env_ip
        # 3. K8s 注入的 Pod IP
        pod_ip = os.environ.get("POD_IP")
        if pod_ip:
            return pod_ip
        # 4. Docker 宿主机 IP（运维注入）
        host_ip = os.environ.get("HOST_IP")
        if host_ip:
            return host_ip
        # 5. 容器默认网关（bridge 网络下为宿主机地址）
        gateway = self._get_default_gateway()
        if gateway:
            return gateway
        # 6. 裸机场景：UDP 探测本机出网 IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((InfraConstant.INFRA_NACOS_PUBLIC_PROBE_HOST, InfraConstant.INFRA_NACOS_PUBLIC_PROBE_PORT))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    @staticmethod
    def _get_default_gateway() -> str | None:
        """读取 Linux 默认网关 IP（/proc/net/route）。

        容器 bridge 网络场景下默认网关即宿主机在容器网络内的地址（如 172.17.0.1），
        注册中心运行于宿主机或同宿主容器时可达；Windows 等无该文件的平台返回 None。
        """
        try:
            with open("/proc/net/route", "r", encoding="utf-8") as f:
                for line in f:
                    fields = line.strip().split()
                    # 第 2 列为目标地址，全 0 表示默认路由；网关字段以小端序十六进制存储
                    if len(fields) >= 3 and fields[1] == "00000000":
                        gateway_hex = fields[2]
                        if gateway_hex != "00000000":
                            return socket.inet_ntoa(bytes.fromhex(gateway_hex)[::-1])
        except (OSError, ValueError):
            pass
        return None
