"""
轮询负载均衡器

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 轮询负载均衡策略：按顺序依次选择可用实例，循环往复，保证各实例被均匀分配。
"""
from __future__ import annotations

import itertools

from web_infra.capabilities.loadbalance.load_balancer_interface import LoadBalancerInterface
from web_infra.capabilities.registry.service_instance import ServiceInstance


class RoundRobinBalancer(LoadBalancerInterface):
    """轮询负载均衡器"""

    def __init__(self) -> None:
        self._counter = itertools.count()

    def choose(self, instances: list[ServiceInstance]) -> ServiceInstance:
        if not instances:
            raise ValueError("没有可用的服务实例")
        index = next(self._counter) % len(instances)
        return instances[index]
