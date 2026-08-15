"""
负载均衡单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证随机/轮询/平滑加权轮询负载均衡策略。
"""
from collections import Counter

import pytest

from web_infra.loadbalance import RandomBalancer, RoundRobinBalancer, WeightedRoundRobinBalancer
from web_infra.registry import ServiceInstance


def test_round_robin_balancer():
    """轮询负载均衡按顺序选择"""
    balancer = RoundRobinBalancer()
    instances = [ServiceInstance(ip="1.1.1.1", port=80), ServiceInstance(ip="2.2.2.2", port=80)]
    assert balancer.choose(instances).ip == "1.1.1.1"
    assert balancer.choose(instances).ip == "2.2.2.2"
    assert balancer.choose(instances).ip == "1.1.1.1"


def test_random_balancer():
    """随机负载均衡从实例中选择"""
    balancer = RandomBalancer()
    instance = ServiceInstance(ip="1.1.1.1", port=80)
    assert balancer.choose([instance]).ip == "1.1.1.1"


def test_weighted_round_robin_proportion():
    """平滑加权轮询按权重比例分配（3:1 时每 4 次选 3/1 次）"""
    balancer = WeightedRoundRobinBalancer()
    instances = [
        ServiceInstance(ip="1.1.1.1", port=80, weight=3.0),
        ServiceInstance(ip="2.2.2.2", port=80, weight=1.0),
    ]
    picks = Counter(balancer.choose(instances).ip for _ in range(12))
    assert picks["1.1.1.1"] == 9
    assert picks["2.2.2.2"] == 3


def test_weighted_round_robin_equal_weights():
    """权重相同时等价于均匀轮询，按顺序交替选择"""
    balancer = WeightedRoundRobinBalancer()
    instances = [
        ServiceInstance(ip="1.1.1.1", port=80, weight=1.0),
        ServiceInstance(ip="2.2.2.2", port=80, weight=1.0),
    ]
    assert balancer.choose(instances).ip == "1.1.1.1"
    assert balancer.choose(instances).ip == "2.2.2.2"
    assert balancer.choose(instances).ip == "1.1.1.1"


def test_weighted_round_robin_skip_non_positive_weight():
    """权重非正的实例不参与调度，仅命中有效实例"""
    balancer = WeightedRoundRobinBalancer()
    instances = [
        ServiceInstance(ip="1.1.1.1", port=80, weight=1.0),
        ServiceInstance(ip="2.2.2.2", port=80, weight=0),
        ServiceInstance(ip="3.3.3.3", port=80, weight=-1.0),
    ]
    for _ in range(6):
        assert balancer.choose(instances).ip == "1.1.1.1"


def test_weighted_round_robin_all_invalid_raises():
    """全部实例权重非正时报错"""
    balancer = WeightedRoundRobinBalancer()
    instances = [ServiceInstance(ip="1.1.1.1", port=80, weight=0)]
    with pytest.raises(ValueError):
        balancer.choose(instances)


def test_weighted_round_robin_empty_raises():
    """实例列表为空时报错"""
    balancer = WeightedRoundRobinBalancer()
    with pytest.raises(ValueError):
        balancer.choose([])


def test_weighted_round_robin_reset_on_instance_change():
    """实例列表变化后自动重置状态，分配比例依然正确"""
    balancer = WeightedRoundRobinBalancer()
    old_instances = [ServiceInstance(ip="1.1.1.1", port=80, weight=2.0)]
    new_instances = [
        ServiceInstance(ip="1.1.1.1", port=80, weight=1.0),
        ServiceInstance(ip="2.2.2.2", port=80, weight=1.0),
    ]
    assert balancer.choose(old_instances).ip == "1.1.1.1"
    # 切换为两个等权实例后应恢复均匀轮询（状态已重置，非从旧权重继续）
    assert balancer.choose(new_instances).ip == "1.1.1.1"
    assert balancer.choose(new_instances).ip == "2.2.2.2"
