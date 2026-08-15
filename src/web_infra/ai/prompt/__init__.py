"""
提示词模板管理模块

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 导出提示词模板模型、存储 SPI（内存默认实现）与填充器（AI 规范 §6.1/§6.2）。
"""
from web_infra.ai.prompt.prompt_template import PromptTemplate
from web_infra.ai.prompt.prompt_template_store_interface import PromptTemplateStoreInterface
from web_infra.ai.prompt.in_memory_prompt_template_store import InMemoryPromptTemplateStore
from web_infra.ai.prompt.prompt_template_filler import PromptTemplateFiller, SIMPLE_PLACEHOLDER_RE

__all__ = [
    "PromptTemplate",
    "PromptTemplateStoreInterface",
    "InMemoryPromptTemplateStore",
    "PromptTemplateFiller",
    "SIMPLE_PLACEHOLDER_RE",
]
