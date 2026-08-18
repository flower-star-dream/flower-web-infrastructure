"""
熔断器开启异常

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 熔断器处于 OPEN 状态时抛出的异常，遵循规范 §7.4。
"""
from __future__ import annotations


class CircuitOpenError(RuntimeError):
    """熔断器处于 OPEN 状态时抛出的异常"""
