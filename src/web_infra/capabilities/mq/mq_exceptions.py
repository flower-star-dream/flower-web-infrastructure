"""
消息队列异常分类

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 消费异常分类（规范 §9.1/S9-1）：可重试异常（网络/超时等临时故障）与
              不可重试异常（业务校验失败等），供重试消费封装与内存队列消费分流治理：
              可重试按次数上限指数退避重试，超限或不可重试进入死信队列（P0-3/S9-7）。
"""
from __future__ import annotations


class RetryableError(Exception):
    """可重试异常（网络超时、Broker 抖动等临时故障，规范 §9.1：重试次数上限内重试）"""


class NonRetryableError(Exception):
    """不可重试异常（业务校验失败、消息格式非法等，重试无意义，直接进入死信队列 P0-3）"""
