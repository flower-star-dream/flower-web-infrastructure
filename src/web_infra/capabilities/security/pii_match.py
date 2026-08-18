"""
单个 PII 识别结果

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 单个 PII 识别结果结构，遵循规范 §17.3 敏感信息脱敏。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PiiMatch:
    """单个 PII 识别结果"""

    category: str
    start: int
    end: int
    text: str
    masked: str | None = None
