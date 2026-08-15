"""
随机负载均衡器

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 随机负载均衡策略：从可用实例中随机选择一个。
"""
from __future__ import annotations

import random

from web_infra.loadbalance.load_balancer_interface import LoadBalancerInterface
from web_infra.registry.service_instance import ServiceInstance


class RandomBalancer(LoadBalancerInterface):
    """随机负载均衡器"""

    def choose(self, instances: list[ServiceInstance]) -> ServiceInstance:
        if not instances:
            raise ValueError("没有可用的服务实例")
        return random.choice(instances)
