"""
提示词模板填充器

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 提示词模板占位符解析与填充（AI 规范 §6.1/§6.2）：
              支持 {var} 风格占位符提取、变量值嵌套占位符哨兵保护（防止二次替换误伤）、
              填充后未替换占位符检测。变量注入仅限参数化，禁止用户输入直接拼入系统提示。
"""
from __future__ import annotations

import re
from typing import Any

# 简单占位符正则：匹配 {variable_name}，不匹配 {{ jinja2 }} 或 {obj.prop}
SIMPLE_PLACEHOLDER_RE = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})")

# 哨兵前缀/后缀：保护变量值中嵌套的 {xxx} 不被二次替换
_PLACEHOLDER_SENTINEL_PREFIX = "\x00PLACEHOLDER_"
_PLACEHOLDER_SENTINEL_SUFFIX = "_\x00"


class PromptTemplateFiller:
    """提示词模板填充器：占位符提取、填充与未替换检测"""

    def extract_variables(self, template: str) -> list[str]:
        """提取模板中使用的所有占位符变量名（去重保持顺序）。

        :param template: 模板文本
        :return: 变量名列表
        """
        return list(dict.fromkeys(SIMPLE_PLACEHOLDER_RE.findall(template)))

    def fill(self, template: str, variables: dict[str, Any], *, raise_on_unfilled: bool = True) -> str:
        """填充模板占位符。

        :param template: 模板文本
        :param variables: 变量名到值的映射（值自动转字符串）
        :param raise_on_unfilled: 填充后仍存在模板占位符时是否抛 ValueError
        :return: 填充后的文本
        :raises ValueError: 存在未替换占位符且 raise_on_unfilled=True
        """
        # 1. 先保护变量值中嵌套的 {xxx}，防止后续替换误伤
        string_values: dict[str, str] = {}
        sentinel_map: dict[str, str] = {}
        for key, value in variables.items():
            protected, sentinels = self._protect_nested_placeholders(str(value))
            string_values[key] = protected
            sentinel_map.update(sentinels)

        # 2. 替换模板中的占位符
        result = template
        for key, value in string_values.items():
            result = result.replace("{" + key + "}", value)

        # 3. 还原被保护的占位符
        for sentinel, original in sentinel_map.items():
            result = result.replace(sentinel, original)

        # 4. 检测未替换占位符
        if raise_on_unfilled:
            remaining = [v for v in self.extract_variables(result) if v in self.extract_variables(template)]
            if remaining:
                raise ValueError(f"模板填充后仍存在未替换占位符: {remaining}，请检查传入变量是否覆盖全部模板变量")

        return result

    def _protect_nested_placeholders(self, text: str) -> tuple[str, dict[str, str]]:
        """将文本中嵌套的 {xxx} 替换为哨兵，返回保护后文本与哨兵映射。

        :param text: 原始文本
        :return: (保护后文本, 哨兵->原始占位符 映射)
        """
        sentinels: dict[str, str] = {}

        def _replace(match: re.Match) -> str:
            var = match.group(1)
            sentinel = f"{_PLACEHOLDER_SENTINEL_PREFIX}{var}{_PLACEHOLDER_SENTINEL_SUFFIX}"
            sentinels[sentinel] = match.group(0)
            return sentinel

        protected = SIMPLE_PLACEHOLDER_RE.sub(_replace, text)
        return protected, sentinels
