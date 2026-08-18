"""
内容安全审核接口

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 内容安全审核抽象（AI 规范 §7.2）：
              输入审核（禁止敏感/危险内容进入模型）与输出审核（拦截违规生成内容）。
              默认提供规则实现，业务可接入第三方审核服务实现该接口。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from web_infra.capabilities.ai.guard_result import GuardResult


class ContentGuardInterface(ABC):
    """内容安全审核接口"""

    @abstractmethod
    def check_input(self, text: str) -> GuardResult:
        """审核输入内容（进入模型前调用）"""
        raise NotImplementedError

    @abstractmethod
    def check_output(self, text: str) -> GuardResult:
        """审核输出内容（返回用户前调用）"""
        raise NotImplementedError
