"""
提示词模板存储接口

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 提示词模板存储抽象（SPI，AI 规范 §6.1），
              支持内存（默认）与业务自定义实现（如数据库 prompt_templates 表）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from web_infra.ai.prompt.prompt_template import PromptTemplate


class PromptTemplateStoreInterface(ABC):
    """提示词模板存储接口"""

    @abstractmethod
    async def load(self, key: str, version: str | None = None) -> PromptTemplate | None:
        """按 key（可指定版本）加载模板；未找到返回 None"""
        raise NotImplementedError

    @abstractmethod
    async def save(self, template: PromptTemplate) -> None:
        """保存/更新模板"""
        raise NotImplementedError
