"""
上下文超长截断重试策略

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 调用大模型捕获"上下文超长"错误后，按解析出的 Token 预算重建上下文并重试
              （AI 规范 §4.2/§4.3）。预算未知时按默认比例截断；重试达到上限仍失败则抛出原异常。
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, TypeVar

from web_infra.capabilities.ai.context_truncator import ContextTruncator
from web_infra.capabilities.ai.context_window_error_parser import ContextWindowErrorParser

T = TypeVar("T")

# 错误文本中无明确数字时的默认保留比例（上下文裁剪为原预算的 50%）
_DEFAULT_BUDGET_RATIO = 0.5

# 上下文工厂：输入 Token 预算（None 表示不限制/首次调用），返回上下文文本
ContextFactory = Callable[[int | None], str]


class ContextWindowRetryPolicy:
    """上下文超长截断重试策略"""

    def __init__(
        self,
        truncator: ContextTruncator | None = None,
        max_attempts: int = 2,
    ) -> None:
        """初始化重试策略。

        :param truncator: 上下文截断器
        :param max_attempts: 最大尝试次数（含首次），默认 2
        """
        self._truncator = truncator or ContextTruncator()
        self._max_attempts = max(1, max_attempts)

    async def run(
        self,
        call: Callable[[str], Awaitable[T]],
        context_factory: ContextFactory,
        model_code: str | None = None,
    ) -> T:
        """执行带上下文超长重试的模型调用。

        :param call: 模型调用函数，入参为上下文文本，返回任意结果
        :param context_factory: 根据 Token 预算构建上下文（首次预算为 None）
        :param model_code: 模型编码（用于 tokenizer 匹配截断）
        :return: 调用结果
        :raises Exception: 重试耗尽后抛出原始异常
        """
        budget: int | None = None
        for attempt in range(self._max_attempts):
            context = context_factory(budget)
            try:
                return await call(context)
            except Exception as e:
                parsed_budget = ContextWindowErrorParser.parse(e)
                if parsed_budget is None or attempt == self._max_attempts - 1:
                    raise  # 非上下文超长错误或已到最后一次，抛出原异常
                # 有明确超出量时按该量截断；否则按默认比例裁剪
                if parsed_budget > 0:
                    budget = parsed_budget
                elif context:
                    original_tokens = self._truncator.count_tokens(context, model_code)
                    budget = max(int(original_tokens * _DEFAULT_BUDGET_RATIO), 1)
                else:
                    budget = 1
        # 理论上不可达（最后一次尝试抛错）
        raise RuntimeError("unreachable: context window retry exhausted")
