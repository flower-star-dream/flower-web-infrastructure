"""
服务实例模型

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 服务实例信息（ip/port/weight/metadata/healthy），供服务注册发现与负载均衡使用。
              对应 Spring Cloud ServiceInstance 概念，屏蔽具体注册中心差异。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ServiceInstance:
    """服务实例信息"""

    ip: str
    port: int
    weight: float = 1.0
    metadata: dict = field(default_factory=dict)
    healthy: bool = True

    @property
    def host(self) -> str:
        """完整主机地址（ip:port）"""
        return f"{self.ip}:{self.port}"

    @property
    def url(self) -> str:
        """完整 HTTP URL"""
        return f"http://{self.host}"
