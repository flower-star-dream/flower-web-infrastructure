"""
SPI 注册表统一约定

@Author: 花海
@Date: 2026/08/22 12:00
@Description: 框架 SPI 注册表基类导出（命名空间隔离 / 内置默认保护 / 优先级）。
"""
from web_infra.core.spi.spi_registry import SpiRegistry

__all__ = ["SpiRegistry"]
