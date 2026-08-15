"""
平滑加权轮询负载均衡器

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 平滑加权轮询负载均衡策略（nginx 同款 SWRR 算法）：按权重比例分配请求，
              且同一周期内高权重实例不会连续被选中，流量分布平滑均匀。
              权重取 ServiceInstance.weight，非正权重实例不参与调度。
"""
from __future__ import annotations

from web_infra.loadbalance.load_balancer_interface import LoadBalancerInterface
from web_infra.registry.service_instance import ServiceInstance


class WeightedRoundRobinBalancer(LoadBalancerInterface):
    """平滑加权轮询负载均衡器（SWRR，nginx 算法）"""

    def __init__(self) -> None:
        # 实例标识 -> 当前权重（随选择过程动态变化）
        self._current_weight: dict[str, float] = {}
        # 实例集合签名（标识 + 权重），用于检测实例列表变化并重置状态
        self._signature: frozenset[tuple[str, float]] = frozenset()

    @staticmethod
    def _key(instance: ServiceInstance) -> str:
        """实例唯一标识（ip:port）"""
        return instance.host

    def _reset_if_changed(self, instances: list[ServiceInstance]) -> None:
        """实例集合或权重变化时重置当前权重，避免状态漂移"""
        signature = frozenset((self._key(i), i.weight) for i in instances)
        if signature != self._signature:
            self._signature = signature
            self._current_weight = {self._key(i): 0.0 for i in instances}

    def choose(self, instances: list[ServiceInstance]) -> ServiceInstance:
        """按平滑加权轮询选择一个实例：当前权重 += 配置权重，选最大值，选中者 -= 总权重"""
        # 过滤权重非正（不可参与调度）的实例
        actives = [i for i in instances if i.weight > 0]
        if not actives:
            raise ValueError("没有可用的服务实例")
        self._reset_if_changed(actives)

        total = sum(i.weight for i in actives)
        # 1. 各实例当前权重累加配置权重
        for inst in actives:
            self._current_weight[self._key(inst)] += inst.weight
        # 2. 选择当前权重最大的实例（并列取首个）
        best = max(actives, key=lambda i: self._current_weight[self._key(i)])
        # 3. 被选中实例当前权重减去总权重
        self._current_weight[self._key(best)] -= total
        return best
