"""
日志输出通道 SPI 注册表

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 日志输出通道 SPI 注册表：按名称注册/查询 LogSinkInterface 工厂，
              内置 console（控制台）/ file（文件，按天轮转 + 保留天数）通道；
              用户自定义通道（远端日志平台、消息队列等）经 register 注册后，
              在 app.logging.sinks 配置中声明即启用，未注册的名称配置期快速失败。
              继承 SpiRegistry 基类：内置默认落框架命名空间（受保护）。
"""
from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from typing import Any, Callable

from web_infra.core.spi import SpiRegistry
from web_infra.infra.logging.log_sink_interface import LogSinkInterface

#: 日志通道工厂签名：入参通道配置（app.logging.sinks.<name> 或内置通道解析出的选项），返回日志通道实现
LogSinkFactory = Callable[[dict[str, Any] | None], LogSinkInterface]


class ConsoleLogSink:
    """控制台日志通道（内置）"""

    def create_handler(self, options: dict[str, Any] | None = None) -> logging.Handler:
        return logging.StreamHandler()


class FileLogSink:
    """文件日志通道（内置，按天轮转 + 保留天数，规范 §17.2 要求保留 ≥30 天）"""

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self._options = options or {}

    def create_handler(self, options: dict[str, Any] | None = None) -> logging.Handler:
        merged = {**self._options, **(options or {})}
        log_file = merged.get("file")
        if not log_file:
            raise ValueError("file 日志通道需要配置 file 路径（如 configure_logging(log_file=...) 或 app.logging.file）")
        # 目录自动创建（TimedRotatingFileHandler 不负责建目录）
        parent = os.path.dirname(log_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        retention_days = int(merged.get("retention_days") or 30)
        return TimedRotatingFileHandler(log_file, when="midnight", backupCount=retention_days, encoding="utf-8")


class LogSinkRegistry(SpiRegistry):
    """日志输出通道注册表（类级注册，全局装配；同名覆盖）"""

    @classmethod
    def create(cls, name: str, options: dict[str, Any] | None = None) -> LogSinkInterface:
        """按名实例化日志通道；未注册抛 KeyError（配置期由 configure_logging 捕获转明确报错）"""
        return cls.get(name)(options)


def _console_factory(options: dict[str, Any] | None = None) -> LogSinkInterface:
    return ConsoleLogSink()


def _file_factory(options: dict[str, Any] | None = None) -> LogSinkInterface:
    return FileLogSink(options)


# 内置通道条目（模块导入即注册，幂等）
LogSinkRegistry.register("console", _console_factory, namespace=LogSinkRegistry.FRAMEWORK_NAMESPACE)
LogSinkRegistry.register("file", _file_factory, namespace=LogSinkRegistry.FRAMEWORK_NAMESPACE)
