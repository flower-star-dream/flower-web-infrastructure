"""
提示词组装器（注入防护）

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 提示词组装与注入防护（AI 规范 §7.2）：
              系统提示词与用户输入按消息角色隔离（用户输入不可覆盖系统提示词）；
              系统提示模板经参数化变量填充（复用 PromptTemplateFiller，禁止裸拼接）；
              工具调用白名单校验，禁止用户诱导越权工具。
"""
from __future__ import annotations

from typing import Any, Sequence

from web_infra.capabilities.ai.chat_message import ChatMessage
from web_infra.capabilities.ai.chat_role_enum import ChatRole
from web_infra.capabilities.ai.prompt.prompt_template_filler import PromptTemplateFiller
from web_infra.infra.error import CommonErrorCode


class PromptAssembler:
    """提示词组装器：角色隔离 + 参数化注入 + 工具白名单"""

    def __init__(self, filler: PromptTemplateFiller | None = None) -> None:
        self._filler = filler or PromptTemplateFiller()

    def assemble(
        self,
        *,
        system_prompt: str,
        user_input: str,
        history: list[ChatMessage] | None = None,
    ) -> list[ChatMessage]:
        """组装对话消息列表（系统提示词权威，用户输入按 USER 角色隔离，不可覆盖系统提示）。

        :param system_prompt: 系统提示词（权威，由后端组装，不下发前端）
        :param user_input: 用户输入（按不可信数据处理，置于 USER 消息）
        :param history: 历史消息（可选）
        :return: 消息列表（system → history → user）
        """
        messages = [ChatMessage(role=ChatRole.SYSTEM, content=system_prompt)]
        if history:
            messages.extend(history)
        messages.append(ChatMessage(role=ChatRole.USER, content=user_input))
        return messages

    def assemble_with_template(
        self,
        *,
        template: str,
        variables: dict[str, Any],
        user_input: str,
        history: list[ChatMessage] | None = None,
    ) -> list[ChatMessage]:
        """按系统提示模板参数化组装（系统提示变量注入，禁止用户输入裸拼接进系统提示）。

        :param template: 系统提示模板（{var} 占位符）
        :param variables: 模板变量（业务数据，非原始用户输入）
        :param user_input: 用户输入（置于 USER 消息，与系统提示隔离）
        :param history: 历史消息（可选）
        :return: 消息列表
        """
        system_prompt = self._filler.fill(template, variables)
        return self.assemble(system_prompt=system_prompt, user_input=user_input, history=history)

    def validate_tools(self, tool_names: Sequence[str], whitelist: Sequence[str]) -> None:
        """校验工具调用白名单（AI 规范 §7.2：工具调用白名单化，禁止越权工具）。

        :param tool_names: 本次请求涉及的工具名
        :param whitelist: 允许的工具白名单
        :raises BizException: 存在白名单外工具时抛 E1-PARAM-000
        """
        whitelist_set = set(whitelist)
        illegal = [name for name in tool_names if name not in whitelist_set]
        if illegal:
            raise CommonErrorCode.PARAM_INVALID.to_exception(message=f"工具调用不在白名单内：{illegal}")
