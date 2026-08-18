"""
日志输出通道 SPI 接口

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 日志输出通道 SPI：开发者可自定义日志存储位置/传输方式（远端日志平台、消息队列、
              自研轮转方案等），实现 LogSinkInterface 并经 LogSinkRegistry 注册后，
              在 app.logging.sinks 配置中声明即启用，无需改动框架装配代码。
              框架统一为通道返回的 Handler 挂载格式器（text/json，规范 §17.2）与
              上下文/脱敏过滤器（ContextFilter §17.1 / SensitiveDataFilter §17.3），
              保证与内置通道输出格式一致。
"""
from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LogSinkInterface(Protocol):
    """日志输出通道 SPI"""

    def create_handler(self, options: dict[str, Any] | None = None) -> logging.Handler:
        """构造日志输出 Handler。

        返回标准库 logging.Handler（如 StreamHandler / 自定义 Handler 子类）；框架统一挂载：
        - 格式器：按 app.logging.format 配置（text/json），保证与内置通道一致（规范 §17.2）；
        - 过滤器：ContextFilter（TraceId/用户上下文，§17.1）与 SensitiveDataFilter（脱敏，§17.3）。

        :param options: 通道配置（app.logging.sinks.<name> 段）；实现通常在构造时已持有配置，可忽略
        :return: 日志输出 Handler
        """
        ...
