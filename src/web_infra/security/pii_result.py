"""
PII 检测结果

@Author: 花海
@Date: 2026/08/14 10:00
@Description: PII 检测结果结构，遵循规范 §17.3 敏感信息脱敏。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from web_infra.security.pii_match import PiiMatch


@dataclass
class PiiResult:
    """PII 检测结果"""

    has_pii: bool = False
    matches: list[PiiMatch] = field(default_factory=list)
    masked_text: str | None = None
