"""
上下文截断器

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 按 Token 预算截断上下文文本（AI 规范 §4.3：上下文超长时截断后重试）。
              基于 TokenCounter 精确计数，超预算按比例裁剪前缀并递减校准。
"""
from __future__ import annotations

from web_infra.utils.token_counter import TokenCounter


class ContextTruncator:
    """按 Token 预算截断文本"""

    def __init__(self, token_counter: TokenCounter | None = None) -> None:
        self._token_counter = token_counter or TokenCounter.get_instance()

    def count_tokens(self, text: str, model_code: str | None = None) -> int:
        """统计文本 Token 数（透传 TokenCounter）"""
        return self._token_counter.count_tokens(text, model_code)

    def truncate(self, text: str, budget_tokens: int, model_code: str | None = None) -> str:
        """将文本截断到预算 Token 内（保留前缀，预算 <= 0 返回空串）。

        :param text: 原始文本
        :param budget_tokens: Token 预算（>0）
        :param model_code: 模型编码（用于精确 tokenizer 匹配）
        :return: 截断后文本
        """
        if not text or budget_tokens <= 0:
            return ""
        if self._token_counter.count_tokens(text, model_code) <= budget_tokens:
            return text

        # 按比例粗裁前缀，再递减校准到预算内
        ratio = max(budget_tokens / max(self._token_counter.count_tokens(text, model_code), 1), 0.05)
        cut = max(int(len(text) * ratio), 1)
        result = text[:cut]
        while result and self._token_counter.count_tokens(result, model_code) > budget_tokens:
            result = result[: max(int(len(result) * 0.9), len(result) - 100)]
        return result
