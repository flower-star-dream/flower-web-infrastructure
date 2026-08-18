"""
规则内容安全审核器

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 基于关键词正则的内容安全审核（默认实现，AI 规范 §7.2）。
              输入默认放行 + 敏感规则阻断；输出按危险/敏感分级（危险阻断、敏感警告）。
              业务可通过注册自定义规则（规则名 -> 正则）扩展，或整体替换为第三方审核实现。
"""
from __future__ import annotations

import re
from typing import Mapping

from web_infra.capabilities.ai.content_guard_interface import ContentGuardInterface
from web_infra.capabilities.ai.guard_action import GuardAction
from web_infra.capabilities.ai.guard_result import GuardResult

# 默认危险规则（输入输出均阻断）：涉恐、违禁等
_DEFAULT_BLOCK_RULES: dict[str, str] = {
    "violence": r"枪支|弹药|爆炸物|砍人|杀人方法",
    "dangerous": r"制造.*毒品|自杀方法|自残",
}

# 默认警告规则（仅输出警告）：涉敏、医疗免责场景提示
_DEFAULT_WARN_RULES: dict[str, str] = {
    "sensitive": r"政治敏感|色情|赌博网站",
    "medical_self_medication": r"自行服药|停用药物|代替医生",
}


class RuleBasedContentGuard(ContentGuardInterface):
    """规则内容审核器（默认实现）"""

    def __init__(
        self,
        block_rules: Mapping[str, str] | None = None,
        warn_rules: Mapping[str, str] | None = None,
    ) -> None:
        """初始化审核器。

        :param block_rules: 阻断规则（规则名 -> 正则），默认内置危险规则
        :param warn_rules: 警告规则（规则名 -> 正则），默认内置敏感规则
        """
        merged_block = dict(_DEFAULT_BLOCK_RULES)
        merged_warn = dict(_DEFAULT_WARN_RULES)
        if block_rules:
            merged_block.update(block_rules)
        if warn_rules:
            merged_warn.update(warn_rules)
        self._block_patterns = {name: re.compile(pattern) for name, pattern in merged_block.items()}
        self._warn_patterns = {name: re.compile(pattern) for name, pattern in merged_warn.items()}

    def check_input(self, text: str) -> GuardResult:
        """输入审核：命中阻断规则即 BLOCK，否则放行"""
        if not text:
            return GuardResult(action=GuardAction.PASS)
        for name, pattern in self._block_patterns.items():
            if pattern.search(text):
                return GuardResult(
                    action=GuardAction.BLOCK,
                    rules=[name],
                    message=f"输入包含敏感内容（{name}），已阻断",
                )
        return GuardResult(action=GuardAction.PASS)

    def check_output(self, text: str) -> GuardResult:
        """输出审核：命中阻断规则 BLOCK；否则命中警告规则 WARN；否则放行"""
        if not text:
            return GuardResult(action=GuardAction.PASS)
        for name, pattern in self._block_patterns.items():
            if pattern.search(text):
                return GuardResult(
                    action=GuardAction.BLOCK,
                    rules=[name],
                    message=f"输出包含违禁内容（{name}），已拦截",
                )
        for name, pattern in self._warn_patterns.items():
            if pattern.search(text):
                return GuardResult(
                    action=GuardAction.WARN,
                    rules=[name],
                    message=f"输出包含敏感提示（{name}），请注意甄别",
                )
        return GuardResult(action=GuardAction.PASS)
