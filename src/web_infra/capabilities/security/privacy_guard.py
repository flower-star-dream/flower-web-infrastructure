"""
PII 检测与脱敏

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 基于正则识别常见个人敏感信息并提供脱敏（手机/身份证/银行卡/邮箱/中文姓名/地址），
              遵循规范 §17.3 敏感信息脱敏与 §15.3 数据安全分级。
"""
from __future__ import annotations

import re

from web_infra.capabilities.security.pii_match import PiiMatch
from web_infra.capabilities.security.pii_result import PiiResult


class PrivacyGuard:
    """PII 检测与脱敏器"""

    MOBILE_RE = re.compile(r"(?<![0-9])(1[3-9]\d{9})(?![0-9])")
    ID_CARD_RE = re.compile(r"(?<![0-9])\d{17}[\dXx](?![0-9])")
    BANK_CARD_RE = re.compile(r"(?<![0-9])\d{16,19}(?![0-9])")
    EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    CHINESE_NAME_RE = re.compile(r"(?:姓\s*名|姓名|联系人|姓名[:：]|我叫|我是|患者|家属|医生)\s*[:：]?\s*([\u4e00-\u9fa5]{2,4})")
    ADDRESS_RE = re.compile(r"([\u4e00-\u9fa5]{2,5}(?:省|市|自治区|县|区))(?:[\u4e00-\u9fa5]{1,20}(?:街道|路|街|巷|镇|乡))?[\u4e00-\u9fa5]{0,20}[\d\-a-zA-Z]{1,20}(?:号|室|栋|单元)")

    def detect(self, text: str) -> PiiResult:
        """检测文本中的 PII 信息"""
        result = PiiResult()
        matches: list[PiiMatch] = []
        for pattern, category, mask_fn in [
            (self.MOBILE_RE, "mobile", self._mask_mobile),
            (self.ID_CARD_RE, "id_card", self._mask_id_card),
            (self.BANK_CARD_RE, "bank_card", self._mask_bank_card),
            (self.EMAIL_RE, "email", self._mask_email),
            (self.CHINESE_NAME_RE, "chinese_name", self._mask_chinese_name),
            (self.ADDRESS_RE, "address", self._mask_address),
        ]:
            for m in pattern.finditer(text):
                value = m.group(1) if m.groups() else m.group(0)
                matches.append(PiiMatch(category=category, start=m.start(), end=m.end(), text=value, masked=mask_fn(value)))

        if matches:
            result.has_pii = True
            result.matches = self._deduplicate(matches)
            result.masked_text = self._apply_masks(text, result.matches)
        else:
            result.masked_text = text
        return result

    def mask(self, text: str) -> str:
        """对文本脱敏"""
        return self.detect(text).masked_text or text

    def _deduplicate(self, matches: list[PiiMatch]) -> list[PiiMatch]:
        """按位置去重"""
        matches.sort(key=lambda x: x.start)
        deduped: list[PiiMatch] = []
        for m in matches:
            if not deduped or m.start >= deduped[-1].end:
                deduped.append(m)
        return deduped

    def _apply_masks(self, text: str, matches: list[PiiMatch]) -> str:
        """按位置替换"""
        parts: list[str] = []
        last_end = 0
        for m in matches:
            parts.append(text[last_end:m.start])
            parts.append(m.masked if m.masked is not None else text[m.start:m.end])
            last_end = m.end
        parts.append(text[last_end:])
        return "".join(parts)

    @staticmethod
    def _mask_mobile(value: str) -> str:
        return f"{value[:3]}****{value[7:]}" if len(value) == 11 else value[:2] + "****" + value[-2:]

    @staticmethod
    def _mask_id_card(value: str) -> str:
        return f"{value[:6]}********{value[14:]}"

    @staticmethod
    def _mask_bank_card(value: str) -> str:
        return "****" + value[-4:]

    @staticmethod
    def _mask_email(value: str) -> str:
        parts = value.split("@")
        if len(parts) != 2:
            return value
        local = parts[0]
        masked_local = local[0] + "***" + local[-1] if len(local) > 1 else "***"
        return f"{masked_local}@{parts[1]}"

    @staticmethod
    def _mask_chinese_name(value: str) -> str:
        return value[0] + "**" if len(value) >= 2 else "**"

    @staticmethod
    def _mask_address(value: str) -> str:
        if len(value) <= 6:
            return value[:2] + "**" + value[-2:] if len(value) >= 4 else "**"
        return value[:4] + "****" + value[-2:]
