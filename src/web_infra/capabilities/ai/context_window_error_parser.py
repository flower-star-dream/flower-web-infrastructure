"""
上下文超长错误解析器

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 解析大模型供应商"上下文超长"错误，提取所需的 Token 预算
              （AI 规范 §4.2/§4.3：上下文超长属于可重试语义错误，需截断后重试）。
              支持 OpenAI 风格错误文本，未命中返回 None。
"""
from __future__ import annotations

import re

# OpenAI 风格：This model's maximum context length is 128000 tokens. However you requested 128100 tokens
_REQUESTED_TOKENS_RE = re.compile(r"you requested (\d+) tokens?", re.IGNORECASE)
# 上下文上限：maximum context length is X tokens
_MAX_CONTEXT_LENGTH_RE = re.compile(r"maximum context length is (\d+) tokens?", re.IGNORECASE)
# 通用超长提示：context length exceeded / context window is too small
_EXCEEDED_RE = re.compile(r"context (length|window).{0,20}(exceeded|too (small|long))", re.IGNORECASE)


class ContextWindowErrorParser:
    """上下文超长错误解析器"""

    @classmethod
    def parse(cls, error: Exception | str) -> int | None:
        """从错误中提取需要的 Token 预算。

        优先取"requested X tokens"（明确超出量）；其次取上下文上限；
        仅命中通用提示但无数字时返回 0（表示需按默认比例截断）。
        未识别返回 None（非上下文超长错误，不应按此重试）。

        :param error: 异常对象或错误文本
        :return: Token 预算（>0 具体值，0 表示需截断但未知具体量）；无法解析返回 None
        """
        message = str(error)
        requested = _REQUESTED_TOKENS_RE.search(message)
        if requested:
            return int(requested.group(1))
        max_len = _MAX_CONTEXT_LENGTH_RE.search(message)
        if max_len:
            return int(max_len.group(1))
        if _EXCEEDED_RE.search(message):
            return 0
        return None
