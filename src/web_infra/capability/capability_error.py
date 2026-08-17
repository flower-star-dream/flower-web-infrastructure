"""
能力异常

@Author: 花海
@Date: 2026/08/17 16:00
@Description: 能力注册 / 解析 / 启用过程中的异常：未知能力、依赖循环、非法注册。
"""
from __future__ import annotations


class CapabilityError(ValueError):
    """能力相关异常：未注册能力 / 依赖循环 / 非法注册"""
