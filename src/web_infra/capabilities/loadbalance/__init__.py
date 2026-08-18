"""
负载均衡模块

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 负载均衡策略抽象与实现聚合导出，遵循规范 §3（SPI）与 §1.3 微服务适配。
              提供 LoadBalancerInterface 抽象 + 随机/轮询/平滑加权轮询实现，用户可自定义策略，防止技术栈锁定。
"""
from web_infra.capabilities.loadbalance.load_balancer_interface import LoadBalancerInterface
from web_infra.capabilities.loadbalance.random_balancer import RandomBalancer
from web_infra.capabilities.loadbalance.round_robin_balancer import RoundRobinBalancer
from web_infra.capabilities.loadbalance.weighted_round_robin_balancer import WeightedRoundRobinBalancer

__all__ = ["LoadBalancerInterface", "RandomBalancer", "RoundRobinBalancer", "WeightedRoundRobinBalancer"]
