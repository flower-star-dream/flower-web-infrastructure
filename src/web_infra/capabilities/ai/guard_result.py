"""
内容审核结果模型

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 内容安全审核结果（AI 规范 §7.2）：审核动作 + 命中的规则列表。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from web_infra.capabilities.ai.guard_action import GuardAction


class GuardResult(BaseModel):
    """内容审核结果"""

    action: GuardAction = Field(description="审核动作：BLOCK/WARN/PASS")
    rules: list[str] = Field(default_factory=list, description="命中的规则名称列表")
    message: str = Field(default="", description="审核提示信息（BLOCK/WARN 时给出原因）")

    @property
    def blocked(self) -> bool:
        """是否阻断"""
        return self.action is GuardAction.BLOCK

    @property
    def passed(self) -> bool:
        """是否放行"""
        return self.action is GuardAction.PASS
