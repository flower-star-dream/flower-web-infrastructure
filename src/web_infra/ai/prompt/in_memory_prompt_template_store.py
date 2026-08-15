"""
内存提示词模板存储

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 基于内存字典的提示词模板存储（默认实现），
              多实例部署需替换为数据库等共享存储实现 PromptTemplateStoreInterface。
"""
from __future__ import annotations

import asyncio

from web_infra.ai.prompt.prompt_template import PromptTemplate
from web_infra.ai.prompt.prompt_template_store_interface import PromptTemplateStoreInterface


class InMemoryPromptTemplateStore(PromptTemplateStoreInterface):
    """内存提示词模板存储（默认实现）"""

    def __init__(self) -> None:
        self._templates: dict[str, PromptTemplate] = {}  # key -> 最新版本模板
        # 线程安全：与同框架其他内存存储保持一致（asyncio.Lock，单事件循环内互斥）
        self._lock = asyncio.Lock()

    async def load(self, key: str, version: str | None = None) -> PromptTemplate | None:
        async with self._lock:
            template = self._templates.get(key)
            if template is None:
                return None
            if version is not None and template.version != version:
                return None
            return template

    async def save(self, template: PromptTemplate) -> None:
        async with self._lock:
            self._templates[template.key] = template
