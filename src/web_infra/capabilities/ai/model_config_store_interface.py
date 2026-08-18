"""
模型配置来源接口

@Author: 花海
@Date: 2026/08/14 23:00
@Description: 模型配置来源 SPI：用户可接入数据库/配置中心等实现（AI 规范 §2/§3/§17.4）。
              load_all 供「页面化模型配置自动注册」使用：按配置清单批量加载并自动同步至 SPI 注册表。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from web_infra.capabilities.ai.model_config import ModelConfig


@runtime_checkable
class ModelConfigStoreInterface(Protocol):
    """模型配置来源 SPI：用户可接入数据库/配置中心等实现"""

    async def load(self, model_code: str | None = None) -> ModelConfig | None:
        """加载模型配置，未找到返回 None"""
        ...

    async def load_all(self) -> list[ModelConfig]:
        """加载全部模型配置（页面化配置自动注册依据，规范 §17.4/§3.2）"""
        ...
