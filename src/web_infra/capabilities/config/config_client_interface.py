"""
配置中心接口

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 配置中心通用接口（SPI），遵循规范 §15.2 配置安全。屏蔽 Nacos/Apollo 等配置中心差异，
              用户可自行实现替换，防止技术栈锁定。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ConfigClientInterface(Protocol):
    """配置中心通用接口（SPI）"""

    async def get_config(self, data_id: str, group: str | None = None) -> str:
        """拉取指定配置内容（字符串），不存在返回空字符串"""
        ...

    def get_config_sync(self, data_id: str, group: str | None = None) -> str:
        """同步拉取配置内容（用于已存在事件循环的场景）"""
        ...

    async def close(self) -> None:
        """释放底层资源"""
        ...
