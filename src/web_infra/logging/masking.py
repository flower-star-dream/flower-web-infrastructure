"""
敏感信息脱敏

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 日志敏感信息脱敏工具，遵循规范 §17.3。
              - 密码/密钥/Token -> ******
              - 手机号中间四位打码（138****1234）
              - 银行卡仅保留后 4 位
              - 身份证号中间打码
"""
from __future__ import annotations

import re

# 脱敏占位符
_MASK = "******"

# 手机号：1 开头 + 10 位数字
_PHONE_RE = re.compile(r"\b1\d{2}(\d{4})\d{4}\b")
# 身份证号：18 位（或 15 位）
_ID_CARD_RE = re.compile(r"\b\d{6}(?:\d{8}|\d{4})(?:\d{2}[\dXx]|\d{3})\b")
# 银行卡号：13-19 位数字
_BANK_CARD_RE = re.compile(r"\b\d{13,19}\b")


def mask_phone(text: str) -> str:
    """手机号脱敏：138****1234"""
    return _PHONE_RE.sub(lambda m: m.group(0)[:3] + "****" + m.group(0)[-4:], text)


def mask_id_card(text: str) -> str:
    """身份证号脱敏：保留前 6 后 4，中间打码"""
    return _ID_CARD_RE.sub(
        lambda m: m.group(0)[:6] + _MASK + m.group(0)[-4:],
        text,
    )


def mask_bank_card(text: str) -> str:
    """银行卡号脱敏：仅保留后 4 位"""
    return _BANK_CARD_RE.sub(lambda m: _MASK + m.group(0)[-4:], text)


def mask_secret(text: str) -> str:
    """将常见敏感字段值替换为掩码（password/token/secret/key 等）。

    覆盖 yml（`key: value`）、query（`key=value`）与 JSON 引号键值（`"key": "value"`）三种形式。
    """
    return re.sub(
        r"""(?ix)
        (password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key)
        \s*"?\s*[:=]\s*"?[^,"'{}<>\[\]\s]+"? 
        """,
        r"\1=******",
        text,
    )


def mask(text: str) -> str:
    """综合脱敏：依次对密钥、手机号、身份证号、银行卡号脱敏"""
    if not text:
        return text
    return mask_bank_card(mask_id_card(mask_phone(mask_secret(text))))
