"""
负载均衡器接口

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 负载均衡策略抽象接口（SPI），从可用实例列表中选择一个实例，用户可自定义策略。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from web_infra.capabilities.registry.service_instance import ServiceInstance


class LoadBalancerInterface(ABC):
    """负载均衡器抽象接口（SPI）"""

    @abstractmethod
    def choose(self, instances: list[ServiceInstance]) -> ServiceInstance:
        """从实例列表中选择一个实例"""
        raise NotImplementedError
