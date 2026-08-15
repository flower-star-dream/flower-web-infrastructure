"""
缓存 Key 生成器

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 缓存 Key 统一生成器，遵循规范 §5.6/§5.7（占位符模板 + 统一生成方法）。
"""
from __future__ import annotations

import re

from web_infra.error.param_exception import ParamException

# 占位符匹配：{xxx}
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

# 动态段非法字符（禁止为空或含分隔符/空白，见规范 §5.6 动态段校验）
_INVALID_SEGMENT_RE = re.compile(r"[\s:]+")


class KeyBuilder:
    """缓存 Key / 含动态段字符串的统一生成器"""

    @staticmethod
    def build(template: str, *args: object) -> str:
        """按占位符模板注入动态段生成最终 Key。

        模板如 "web:order:v1:detail:{id}"，按位置将 *args 依次注入占位符。
        动态段为空或含非法字符时抛出参数异常（规范 §5.6）。
        """
        segments = list(args)

        def _replacer(match: re.Match[str]) -> str:
            if not segments:
                raise ParamException(message=f"模板 {template} 动态段参数不足")
            value = str(segments.pop(0))
            if not value or _INVALID_SEGMENT_RE.search(value):
                raise ParamException(message=f"动态段值非法：{value!r}")
            return value

        result = _PLACEHOLDER_RE.sub(_replacer, template)
        if segments:
            raise ParamException(message=f"模板 {template} 动态段参数过多")
        return result
